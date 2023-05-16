#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Purpose
-------

Accepts a matrix with results from the AlleleCall process of
chewBBACA and determines the pairwise allelic differences to
create a distance matrix. It also determines the number of
shared loci to create a matrix with those values. The 'INF-'
prefix is removed and ASM, ALM, NIPH, NIPHEM, PLOT3, PLOT5,
LNF and LOTSC classifications are substituted by '0' before
performing pairwise comparisons.

Code documentation
------------------
"""


import os
import csv
import time
import math
import shutil
import pickle
import random
import argparse
import traceback
from multiprocessing import Pool

import numpy as np
import pandas as pd

# these modules must be in the same directory
#import mask_matrix as mm

try:
    from utils import (
        constants as ct,
        file_operations as fo,
        fasta_operations as fao,
        sequence_manipulation as sm,
        iterables_manipulation as im,
        multiprocessing_operations as mo,
        mask_matrix as mm)
except ModuleNotFoundError:
    from CHEWBBACA.utils import (
        constants as ct,
        file_operations as fo,
        fasta_operations as fao,
        sequence_manipulation as sm,
        iterables_manipulation as im,
        multiprocessing_operations as mo,
        mask_matrix as mm)


def tsv_to_nparray(input_file, array_dtype='int32'):
    """Read matrix of allelic profiles and convert to Numpy array.

    File lines are read as a generator to exclude the sample identifier
    and avoid loading huge files into memory.

    Parameters
    ----------
    input_file : str
        Path to the TSV file with the matrix with
        allelic profiles.
    array_dtype : str
        Array data type.

    Returns
    -------
    np_array : ndarray
        Numpy array with the numeric values for
        all allelic profiles.
    """
    # import matrix without column and row identifiers
    with open(input_file, 'r') as infile:
        lines = ('\t'.join(line.split('\t')[1:])
                 for line in infile)
        # dtype=float32 should be faster than integer dtypes
        # but runs faster with dtype=int32 in test setup
        # dtype=int32 supports max integer of 2,147,483,647
        # should be safe even when arrays are multiplied
        np_array = np.genfromtxt(fname=lines, delimiter='\t',
                                 dtype=array_dtype, skip_header=1)

        # need to reshape array to 2D if it only has info for one sample
        try:
            # if it does not have columns it needs to be reshaped
            np_array.shape[1]
        except Exception:
            np_array = np.array([np_array])

    return np_array


def compute_distances(indexes, np_matrix, genome_ids, tmp_directory):
    """Compute pairwise allelic differences and number of shared loci.

    Parameters
    ----------
    indexes : list
        List with the line index of the allelic profiles
        that will be processed.
    np_matrix : ndarray
        Numpy array with dtype=int32 values for allelic profiles.
    genome_ids : list
        List with sample identifiers.
    tmp_directory : str
        Path to temporary directory where pickle files with
        results will be stored.

    Returns
    -------
    output_files : list
        List with the paths to all pickle files that were created
        to store results.
    """
    # multiply one row per cycle to avoid memory overflow
    # read only part of the matrix for huge files and process in chunks?
    output_files = {}
    for i in indexes:
        current_genome = genome_ids[i]
        # get one row to perform pairwise comparisons against whole matrix
        current_row = np_matrix[i:i+1, :]
        # do not multiply against rows that were multiplied against
        # matrix's rows in previous iterations
        # combinations instead of permutations
        permutation_rows = np_matrix[i:, :]

        # multiply 1D-array per whole matrix
        # all non-shared loci will be converted to 0
        # values different than 0 correspond to shared loci
        multiplied = current_row * permutation_rows
        # count number of shared loci, non-zero values
        pairwise_shared_loci = np.count_nonzero(multiplied, axis=-1)

        # subtraction will lead to values different than 0 for loci that have different alleles
        # multiplying ensures that we only keep results for shared loci and not for
        # loci that are not shared and that had value different than 0 from subtraction
        pairwise_allelic_differences = np.count_nonzero(multiplied * (current_row - permutation_rows), axis=-1)

        output_file = os.path.join(tmp_directory, current_genome)
        fo.pickle_dumper([pairwise_shared_loci, pairwise_allelic_differences], output_file)
        output_files[current_genome] = output_file

    return output_files


def join_iterable(iterable, delimiter='\t'):
    """Join the elements of an iterable.

    Parameters
    ----------
    iterable : iter
        Iterable with elements to join (e.g.: list, set, dict).
    delimiter : str, optional
        String used to join all elements. The default is '\t'.

    Returns
    -------
    joined : str
        A string with all elements joined by the delimiter.
    """
    joined = delimiter.join(iterable)

    return joined


def write_text(text, output_file, mode='w'):
    """Write a string to a file.

    Parameters
    ----------
    text : str
        String to write to file.
    output_file : str
        Path to output file.
    mode : str, optional
        Write mode. The default is 'w'.

    Returns
    -------
    None.
    """
    # write matrix to output file
    with open(output_file, mode) as outfile:
        outfile.write(text+'\n')


def write_lines(lines, output_file, mode='w'):
    """Write a matrix to a file.

    Parameters
    ----------
    lines : list
        List of sublists where each sublist corresponds
        to one row with any number of elements.
    output_file : str
        Path to the output file to which the lines will
        be written.
    mode : str, optional
        Write mode. The default is 'w'.

    Returns
    -------
    Writes matrix rows (each sublist of the input list is
    a row) to the output file.
    """
    # join matrix lines into chunk of text
    concat_lines = [join_iterable(line, '\t')
                    for line in lines]
    lines_text = join_iterable(concat_lines, '\n')

    write_text(lines_text, output_file, mode)


def get_sample_ids(input_file, delimiter='\t'):
    r"""Extract the sample identifiers from a matrix with allelic profiles.

    Parameters
    ----------
    input_file : str
        Path to the input file that contains a matrix
        with allelic profiles.
    delimiter : str, optional
        Field delimiter. The default is '\t'.

    Returns
    -------
    sample_ids : list
        List with the sample identifiers.
    """
    with open(input_file, 'r') as infile:
        reader = csv.reader(infile, delimiter=delimiter)
        sample_ids = [line[0] for line in reader][1:]

    return sample_ids


def merge_dictionaries(dictionaries):
    """Merge several dictionaries.

    Parameters
    ----------
    dictionaries : list
        List with several dictionaries to merge.

    Returns
    -------
    merged : dict
        A dictionary that is the result of merging
        all input dictionaries. Common keys will
        be overwritten.
    """
    merged = {}
    for d in dictionaries:
        merged = {**merged, **d}

    return merged


def write_matrices(pickled_results, genome_ids, output_pairwise,
                   output_p, col_ids):
    """Write above diagonal matrices with allelic differences and shared loci.

    Parameters
    ----------
    pickled_results : dict
        Dictionary with sample identifiers as keys
        and paths to binary files with pickled results
        as values.
    genome_ids : list
        List with sample identifiers.
    output_pairwise : str
        Path to the output file to which the matrix
        with pairwise allelic differences will be saved.
    output_p : str
        Path to the output file to which the matrix
        with pairwise shared loci will be saved.
    col_ids: list
        List with sample identifiers to add as headers.

    Returns
    -------
    None.
    """
    sl_lines = [col_ids]
    ad_lines = [col_ids]
    limit = 300
    for g in genome_ids:
        current_file = pickled_results[g]
        # load data
        data = fo.pickle_loader(current_file)

        shared_loci = list(data[0])
        shared_loci = list(map(str, shared_loci))
        allele_diffs = list(data[1])
        allele_diffs = list(map(str, allele_diffs))

        padding = [''] * (len(genome_ids)-len(allele_diffs))

        sl_line = [g] + padding + shared_loci
        sl_lines.append(sl_line)
        ad_line = [g] + padding + allele_diffs
        ad_lines.append(ad_line)

        if len(sl_lines) >= limit or g == genome_ids[-1]:
            write_lines(ad_lines, output_pairwise, mode='a')
            ad_lines = []
            write_lines(sl_lines, output_p, mode='a')
            sl_lines = []

    return True


def concatenate_files(files, output_file, header=None):
    """Concatenate the contents of a set of files.

    Parameters
    ----------
    files : list
        List with the paths to the files to concatenate.
    output_file : str
        Path to the output file that will store the
        concatenation of input files.
    header : str or NoneType
        Specify a header that should be written as the
        first line in the output file.

    Returns
    -------
    output_file : str
        Path to the output file that was created with
        the concatenation of input files.
    """
    with open(output_file, 'w') as of:
        if header is not None:
            of.write(header)
        for f in files:
            with open(f, 'r') as fd:
                shutil.copyfileobj(fd, of)

    return output_file


def transpose_matrix(input_file, output_directory):
    """Transpose lines in a TSV file.

    Parameters
    ----------
    input_file : str
        Path to the input TSV file.
    output_directory : str
        Path to the directory to which intermediate files
        with transposed lines will be written.

    Returns
    -------
    output_transpose : str
        Path to the file with the transposed matrix.
        This file is created by concatenating all
        files saved into `output_directory`.
    """
    file_id = 1
    transpose_files = []
    input_basename = os.path.basename(input_file)
    with open(input_file, 'r') as infile:
        # get columns names
        columns = [e.strip() for e in (infile.__next__()).split('\t')]
        # divide into smaller sets to avoid loading huge files
        num_col_sets = math.ceil(len(columns)/500)
        col_sets = im.divide_list_into_n_chunks(columns, num_col_sets)
        # use Pandas to read columns sets and save transpose
        for c in col_sets:
            # dtype=str or Pandas converts values into floats
            df = pd.read_csv(input_file, usecols=c, delimiter='\t', dtype=str)
            output_basename = input_basename.replace('.tsv', '_{0}.tsv'.format(file_id))
            output_file = os.path.join(output_directory, output_basename)
            # transpose columns
            df = df.T
            # do not save header that contains row indexes
            df.to_csv(output_file, sep='\t', header=False)
            transpose_files.append(output_file)
            file_id += 1

    # concatenate all files with transposed lines
    output_transpose = input_file.replace('.tsv', '_transpose.tsv')
    concatenate_files(transpose_files, output_transpose)

    return output_transpose


def merge_triangular_matrices(upper_matrix, lower_matrix, output_file, matrix_size):
    """Merge two triangular matrices to create a symmetric matrix.

    Parameters
    ----------
    upper_matrix : str
        Path to the TSV file that contains the upper
        triangular matrix.
    lower_matrix : str
        Path to the TSV file that contains the lower
        triangular matrix.
    output_file : str
        Path to the output file to which the symmetric
        matrix will be saved.
    matrix_size : int
        Total number of lines in the triangular matrix.

    Returns
    -------
    None.
    """
    with open(upper_matrix, 'r') as upper_handle, open(lower_matrix, 'r') as lower_handle:
        upper_reader = csv.reader(upper_handle, delimiter='\t')
        lower_reader = csv.reader(lower_handle, delimiter='\t')

        merged_lines = []
        for i in range(matrix_size):
            upper_line = upper_reader.__next__()
            lower_line = lower_reader.__next__()
            merged_line = [e
                           if e != ''
                           else lower_line[i]
                           for i, e in enumerate(upper_line)]
            merged_lines.append(merged_line)

            if len(merged_lines) >= 200 or i == (matrix_size-1):
                write_lines(merged_lines, output_file, mode='a')
                merged_lines = []


def symmetrify_matrix(input_matrix, matrix_size, tmp_directory):
    """Symmetrify a triangular matrix.

    Parameters
    ----------
    input_matrix : str
        Path to TSV file that contains the triangular matrix.
    matrix_size : int
        Total number of lines in input file.
    tmp_directory : str
        Path to the output temporary directory.

    Returns
    -------
    symmetric_output : str
        Path to the output file that contains the symmetric
        matrix.
    """
    output_transpose = transpose_matrix(input_matrix, tmp_directory)

    # merge upper and lower diagonal matrices into symmetric matrix
    symmetric_output = input_matrix.replace('.tsv', '_symmetric.tsv')

    merge_triangular_matrices(input_matrix, output_transpose,
                              symmetric_output, matrix_size)

    # delete files with triangular matrices
    os.remove(input_matrix)
    os.remove(output_transpose)

    return symmetric_output


def main(input_matrix, output_directory, cpu_cores, symmetric):

    # create output directory if it does not exist
    if os.path.isdir(output_directory) is False:
        os.mkdir(output_directory)

    # determine input basename
    input_basename = os.path.basename(input_matrix)
    # remove extension that is after last '.'
    input_basename = '.'.join(input_basename.split('.')[0:-1])

    # define '0' as masking characters for all non-numeric
    # classifications
    classes = ['ALM', 'ASM', 'LNF', 'NIPH',
               'NIPHEM', 'PLOT3', 'PLOT5', 'LOTSC']
    masking_dict = {c: '0' for c in classes}

    print('Masking matrix before determining pairwise distances...', end='')
    output_masked = os.path.join(output_directory,
                                 '{0}_masked.tsv'.format(input_basename))
    total_masked = mm.mask_matrix(input_matrix, masking_dict, output_masked)
    # mask matrix
    print('masked matrix available at {0}'.format(output_masked))

    # create temp directory to store pairwise distances per genome
    tmp_directory = os.path.join(output_directory, 'tmp')
    if os.path.isdir(tmp_directory) is False:
        os.mkdir(tmp_directory)

    # get sample identifiers
    genome_ids = get_sample_ids(input_matrix, delimiter='\t')
    total_genomes = len(genome_ids)

    np_matrix = tsv_to_nparray(output_masked)

    rows_indexes = [i for i in range(len(np_matrix))]
    random.shuffle(rows_indexes)
    # divide inputs into 20 lists for 5% progress resolution
    parallel_inputs = im.divide_list_into_n_chunks(rows_indexes, 20)

    common_args = [[l, np_matrix, genome_ids, tmp_directory, compute_distances] for l in parallel_inputs]

    # increasing cpu cores can greatly increase memory usage
    print('Computing pairwise distances...')
    results = mo.map_async_parallelizer(common_args,
                                        mo.function_helper,
                                        cpu_cores,
                                        show_progress=True)

    merged = merge_dictionaries(results)

    print('\nCreating distance matrix...', end='')
    # create files with headers
    col_ids = ['FILE'] + genome_ids
    output_pairwise = os.path.join(output_directory,
                                   '{0}_allelic_differences.tsv'.format(input_basename))
    output_p = os.path.join(output_directory,
                            '{0}_shared_loci.tsv'.format(input_basename))

    # import arrays per genome and save to matrix file
    results = write_matrices(merged, genome_ids, output_pairwise, output_p, col_ids)

    if symmetric is True:
        # add 1 to include header
        symmetric_allelic_differences = symmetrify_matrix(output_pairwise,
                                                          len(genome_ids)+1,
                                                          tmp_directory)
        symmetric_shared_loci = symmetrify_matrix(output_p,
                                                  len(genome_ids)+1,
                                                  tmp_directory)

    print('done.')
    print('Results available in {0}'.format(output_directory))

    # delete folder with intermediate pickles
    shutil.rmtree(tmp_directory)
