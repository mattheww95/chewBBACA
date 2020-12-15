#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Purpose
-------

This is the main script of the chewBBACA suite.

"""


import os
import sys
import time
import pickle
import shutil
import datetime
import argparse

try:
    from __init__ import __version__
    from allelecall import BBACA
    from createschema import CreateSchema
    from SchemaEvaluator import ValidateSchema
    from PrepExternalSchema import PrepExternalSchema
    from utils import (TestGenomeQuality, profile_joiner,
                       uniprot_find, Extract_cgAlleles,
                       RemoveGenes, sqlite_functions as sq,
                       datetime_utils as dut,
                       io_utils as iut,
                       auxiliary_functions as aux,
                       constants as cnst,
                       parameters_validation as pv,
                       files_utils as fu,
                       sqlite_functions as squt)

    from utils.parameters_validation import ModifiedHelpFormatter

    from CHEWBBACA_NS import (down_schema, load_schema,
                              sync_schema, stats_requests)
except:
    from CHEWBBACA import __version__
    from CHEWBBACA.allelecall import BBACA
    from CHEWBBACA.createschema import CreateSchema
    from CHEWBBACA.SchemaEvaluator import ValidateSchema
    from CHEWBBACA.PrepExternalSchema import PrepExternalSchema
    from CHEWBBACA.utils import (TestGenomeQuality, profile_joiner,
                                 uniprot_find, Extract_cgAlleles,
                                 RemoveGenes, sqlite_functions as sq,
                                 datetime_utils as dut,
                                 io_utils as iut,
                                 auxiliary_functions as aux,
                                 constants as cnst,
                                 parameters_validation as pv,
                                 files_utils as fu,
                                 sqlite_functions as squt)

    from CHEWBBACA.utils.parameters_validation import ModifiedHelpFormatter

    from CHEWBBACA.CHEWBBACA_NS import (down_schema, load_schema,
                                        sync_schema, stats_requests)


version = __version__


@dut.process_timer
def create_schema():

    def msg(name=None):
        # simple command to create schema from genomes
        simple_cmd = ('chewBBACA.py CreateSchema -i <input_files> '
                                                '-o <output_directory> '
                                                '-ptf <ptf_path>')
        # command to create schema from genomes with non-default parameters
        params_cmd = ('chewBBACA.py CreateSchema -i <input_files> '
                                                '-o <output_directory> '
                                                '--ptf <ptf_path>\n'
                                                '\t\t\t    --cpu <cpu_cores> '
                                                '--bsr <blast_score_ratio> '
                                                '--l <minimum_length>\n'
                                                '\t\t\t    --t <translation_table> '
                                                '--st <size_threshold>')
        # command to create schema from single FASTA
        cds_cmd = ('chewBBACA.py CreateSchema -i <input_file> '
                                             '-o <output_directory> '
                                             '--ptf <ptf_path> '
                                             '--CDS')

        usage_msg = ('\nCreate schema from input genomes:\n  {0}\n'
                     '\nCreate schema from input genomes with non-default parameters:\n  {1}\n'
                     '\nCreate schema from single FASTA file:\n  {2}'.format(simple_cmd, params_cmd, cds_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(prog='CreateSchema',
                                     description='Creates a wgMLST '
                                                 'schema based on a '
                                                 'set of input genomes.',
                                     usage=msg(),
                                     formatter_class=ModifiedHelpFormatter)

    parser.add_argument('CreateSchema', nargs='+',
                        help='')

    parser.add_argument('-i', nargs='?', type=str, required=True,
                        dest='input_files',
                        help='Path to the directory that contains the input '
                             'FASTA files. Alternatively, a single file with '
                             'a list of paths to FASTA files, one per line.')

    parser.add_argument('-o', type=str, required=True,
                        dest='output_directory',
                        help='Output directory where the process will store '
                             'intermediate files and create the schema\'s directory.')

    parser.add_argument('--n', type=str, required=False,
                        default='schema_seed', dest='schema_name',
                        help='Name to give to folder that will store the schema files.')

    parser.add_argument('--ptf', type=str, required=False,
                        default=False, dest='ptf_path',
                        help='Path to the Prodigal training file.')

    parser.add_argument('--bsr', type=pv.bsr_type,
                        required=False, default=0.6, dest='blast_score_ratio',
                        help='BLAST Score Ratio value. Sequences with '
                             'alignments with a BSR value equal to or '
                             'greater than this value will be considered '
                             'as sequences from the same gene.')

    parser.add_argument('--l', type=pv.minimum_sequence_length_type,
                        required=False, default=201, dest='minimum_length',
                        help='Minimum sequence length accepted for a '
                             'coding sequence to be included in the schema.')

    parser.add_argument('--t', type=pv.translation_table_type,
                        required=False, default=11, dest='translation_table',
                        help='Genetic code used to predict genes and'
                             ' to translate coding sequences.')

    parser.add_argument('--st', type=pv.size_threshold_type,
                        required=False, default=0.2, dest='size_threshold',
                        help='CDS size variation threshold. At the default '
                             'value of 0.2, alleles with size variation '
                             '+-20 percent will be classified as ASM/ALM.')

    parser.add_argument('--cm', type=str, required=False,
                        default='greedy', dest='clustering_mode',
                        help='The clustering mode. There are two modes: '
                             'greedy and full. Greedy will add sequences '
                             'to a single cluster. Full will add sequences '
                             'to all clusters they share high similarity with.')
    
    parser.add_argument('--ws', type=int, required=False,
                        default=5, dest='word_size',
                        help='Value of k used to decompose protein sequences '
                             'into k-mers.')

    parser.add_argument('--cs', type=float, required=False,
                        default=0.20, dest='clustering_sim',
                        help='Similarity threshold value necessary to '
                             'consider adding a sequence to a cluster. This '
                             'value corresponds to the percentage of shared k-mers.')

    parser.add_argument('--rf', type=float, required=False,
                        default=0.80, dest='representative_filter',
                        help='Similarity threshold value that is considered '
                             'to determine if a sequence belongs to the same '
                             'gene as the cluster representative purely based '
                             'on the percentage of shared k-mers.')
    
    parser.add_argument('--if', type=float, required=False,
                        default=0.80, dest='intra_filter',
                        help='Similarity threshold value that is considered '
                             'to determine if sequences in the same custer '
                             'belong to the same gene. Only one of those '
                             'sequences is kept.')

    parser.add_argument('--cpu', type=pv.verify_cpu_usage, required=False,
                        default=1, dest='cpu_cores',
                        help='Number of CPU cores that will be '
                             'used to run the CreateSchema process '
                             '(will be redefined to a lower value '
                             'if it is equal to or exceeds the total'
                             'number of available CPU cores).')

    parser.add_argument('--b', type=pv.check_blast, required=False,
                        default='', dest='blast_path',
                        help='Path to the BLAST executables.')

    parser.add_argument('--CDS', required=False, action='store_true',
                        dest='cds_input',
                        help='Input is a FASTA file with one representative '
                             'sequence per gene in the schema.')

    parser.add_argument('--pm', required=False, choices=['single', 'meta'],
                        default='single', dest='prodigal_mode',
                        help='Prodigal running mode.')

    parser.add_argument('--no_cleanup', required=False, action='store_true',
                        dest='no_cleanup',
                        help='Delete intermediate files at the end.')

    args = parser.parse_args()
    del args.CreateSchema
    print(args.blast_path)

    prodigal_installed = pv.check_prodigal(cnst.PRODIGAL_PATH)

    # check if ptf exists
    if args.ptf_path is not False:
        ptf_val = aux.check_ptf(args.ptf_path)
        if ptf_val[0] is False:
            sys.exit(ptf_val[1])

    # create output directory
    if not os.path.exists(args.output_directory):
        os.makedirs(args.output_directory)

    if args.cds_input is True:
        args.input_files = os.path.abspath(args.input_files)
    else:
        genomes_list = os.path.join(args.output_directory, 'listGenomes2Call.txt')
        args.input_files = aux.check_input_type(args.input_files, genomes_list)

    # start CreateSchema process
    CreateSchema.main(**vars(args))

    schema_dir = os.path.join(args.output_directory, args.schema_name)
    # copy training file to schema directory
    if args.ptf_path is not False:
        shutil.copy(args.ptf_path, schema_dir)
        # determine PTF checksum
        ptf_hash = fu.hash_file(args.ptf_path, 'rb')
    else:
        ptf_hash = ''

    # write schema config file
    schema_config = aux.write_schema_config(args.blast_score_ratio, ptf_hash,
                                            args.translation_table, args.minimum_length,
                                            version, args.size_threshold,
                                            args.word_size, args.clustering_sim,
                                            args.representative_filter, args.intra_filter,
                                            schema_dir)

    # create hidden file with genes/loci list
    genes_list_file = aux.write_gene_list(schema_dir)

    # remove temporary file with paths
    # to genome files
    if os.path.isfile(args.input_files) and args.cds_input is False:
        os.remove(args.input_files)


@dut.process_timer
def allele_call():

    def msg(name=None):
        # simple command to perform AlleleCall with schema deafult parameters
        simple_cmd = ('chewBBACA.py AlleleCall -i <input_files> '
                                              '-g <schema_directory> '
                                              '-o <output_directory> ')
        # command to perform AlleleCall with non-default parameters
        params_cmd = ('chewBBACA.py AlleleCall -i <input_files> '
                                              '-g <schema_directory> '
                                              '-o <output_directory> '
                                              '--ptf <ptf_path>\n'
                                              '\t\t\t  --cpu <cpu_cores> '
                                              '--bsr <blast_score_ratio> '
                                              '--l <minimum_length>\n'
                                              '\t\t\t  --t <translation_table> '
                                              '--st <size_threshold>')
        # command to perform AlleleCall with single Fasta file
        # cds_cmd = ('chewBBACA.py AlleleCall -i <input_file> '
        #                                    '-o <output_directory> '
        #                                    '--ptf <ptf_path> '
        #                                    '--CDS')

        usage_msg = ('\nPerform AlleleCall with schema default parameters:\n  {0}\n'
                     '\nPerform AlleleCall with non-default parameters:\n  {1}\n'.format(simple_cmd, params_cmd))
                     #'\nPerform AlleleCall with single FASTA file that contains coding sequences:\n  {2}'.format(simple_cmd, params_cmd, cds_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(prog='AlleleCall',
                                     description='Performs allele calling to determine the '
                                                 'allelic profiles of a set of input genomes. '
                                                 'The process identifies new alleles, assigns '
                                                 'an integer identifier to those alleles and '
                                                 'adds them to the schema.',
                                     usage=msg(),
                                     formatter_class=ModifiedHelpFormatter,
                                     epilog='It is strongly advised to perform AlleleCall '
                                            'with the default schema parameters to ensure '
                                            'more consistent results.')

    parser.add_argument('AlleleCall', nargs='+', help='')

    parser.add_argument('-i', nargs='?', type=str, required=True,
                        dest='input_files',
                        help='Path to the directory with the genomes FASTA '
                             'files or to a file with a list of paths to '
                             'the FASTA files, one per line.')

    parser.add_argument('-g', type=str, required=True,
                        dest='schema_directory',
                        help='Path to the schema directory with the'
                             ' genes FASTA files.')

    parser.add_argument('-o', type=str, required=True,
                        dest='output_directory',
                        help='Output directory where the allele '
                             'calling results will be stored.')

    parser.add_argument('--ptf', type=str, required=False,
                        dest='ptf_path',
                        help='Path to the Prodigal training file. '
                             'Default is to get training file from '
                             'schema directory.')

    parser.add_argument('--gl', type=str, required=False,
                        default=False, dest='genes_list',
                        help='Path to a file with the list of genes '
                             'in the schema that the process should '
                             'identify alleles for.')

    parser.add_argument('--bsr', type=pv.bsr_type, required=False,
                        dest='blast_score_ratio',
                        help='BLAST Score Ratio value. Sequences with '
                             'alignments with a BSR value equal to or '
                             'greater than this value will be considered '
                             'as sequences from the same gene.')

    parser.add_argument('--l', type=pv.minimum_sequence_length_type,
                        required=False,
                        dest='minimum_length',
                        help='Minimum sequence length accepted for a '
                             'coding sequence to be included in the schema.')

    parser.add_argument('--t', type=pv.translation_table_type, required=False,
                        dest='translation_table',
                        help='Genetic code used to predict genes and'
                             ' to translate coding sequences '
                             '(default=11).')

    parser.add_argument('--st', type=pv.size_threshold_type, required=False,
                        dest='size_threshold',
                        help='CDS size variation threshold. At the default '
                             'value of 0.2, alleles with size variation '
                             '+-20 percent will be classified as ASM/ALM')

    parser.add_argument('--cpu', type=pv.verify_cpu_usage, required=False, default=1,
                        dest='cpu_cores',
                        help='Number of CPU cores/threads that will be '
                             'used to run the CreateSchema process '
                             '(will be redefined to a lower value '
                             'if it is equal to or exceeds the total'
                             'number of available CPU cores/threads).')

    parser.add_argument('--b', type=pv.check_blast, required=False,
                        default='', dest='blast_path',
                        help='Path to the BLAST executables.')

    parser.add_argument('--contained', action='store_true', required=False,
                        default=False, dest='contained',
                        help=argparse.SUPPRESS)

    parser.add_argument('--CDS', action='store_true', required=False,
                        default=False, dest='cds_input',
                        help=argparse.SUPPRESS)

    parser.add_argument('--json', action='store_true', required=False,
                        dest='json_report',
                        help='Output report in JSON format.')

    parser.add_argument('--fc', action='store_true', required=False,
                        dest='force_continue',
                        help='Continue allele call process that '
                             'was interrupted.')

    parser.add_argument('--fr', action='store_true', required=False,
                        dest='force_reset',
                        help='Force process reset even if there '
                             'are temporary files from a previous '
                             'process that was interrupted.')

    parser.add_argument('--db', required=False, action='store_false',
                        dest='store_profiles',
                        help='If the profiles in the output matrix '
                             'should be stored in the local SQLite '
                             'database.')

    parser.add_argument('--pm', required=False, choices=['single', 'meta'],
                        default='single', dest='prodigal_mode',
                        help='Prodigal running mode.')

    parser.add_argument('--v', required=False, action='store_true',
                        dest='verbose',
                        help='Increased output verbosity during execution.')

    args = parser.parse_args()

    prodigal_installed = pv.check_prodigal(cnst.PRODIGAL_PATH)

    print(vars(args))
    config_file = os.path.join(args.schema_directory, '.schema_config')
    # legacy schemas do not have config file, create one if user wants to continue
    if os.path.isfile(config_file) is False:
        upgraded = aux.upgrade_legacy_schema(args.ptf_path, args.schema_directory,
                                             args.blast_score_ratio, args.translation_table,
                                             args.minimum_length, version,
                                             args.size_threshold, args.force_continue)
        args.ptf_path, args.blast_score_ratio, \
        args.translation_table, args.minimum_length, \
        args.size_threshold = upgraded
    else:
        schema_params = iut.pickle_loader(config_file)
        # chek if user provided different values
        schema_params, unmatch_params, run_params = aux.solve_conflicting_arguments(schema_params, args.ptf_path,
                                                           args.blast_score_ratio, args.translation_table,
                                                           args.minimum_length, args.size_threshold,
                                                           args.force_continue, config_file, args.schema_directory)
        args.ptf_path = run_params['ptf_path']
        args.blast_score_ratio = run_params['bsr']
        args.translation_table = run_params['translation_table']
        args.minimum_length = run_params['minimum_locus_length']
        args.size_threshold = run_params['size_threshold']

        print('\n', schema_params, unmatch_params, run_params)
        print(args)
    # if is a fasta pass as a list of genomes with a single genome,
    # if not check if is a folder or a txt with a list of paths
    if args.genes_list is not False:
        schema_genes = aux.check_input_type(args.genes_list, 'listGenes2Call.txt', args.schema_directory)
    else:
        schema_genes = aux.check_input_type(args.schema_directory, 'listGenes2Call.txt')
    genomes_files = aux.check_input_type(args.input_files, 'listGenomes2Call.txt')

    # determine if schema was downloaded from Chewie-NS
    ns_config = os.path.join(args.schema_directory, '.ns_config')
    ns = os.path.isfile(ns_config)

    print(schema_genes, genomes_files, ns)
    print(args)

    BBACA.main(genomes_files, schema_genes, args.cpu_cores,
               args.output_directory, args.blast_score_ratio,
               args.blast_path, args.force_continue, args.json_report,
               args.verbose, args.force_reset, args.contained,
               args.ptf_path, args.cds_input, args.size_threshold,
               args.translation_table, ns, args.prodigal_mode)

    if args.store_profiles is True:
        updated = squt.store_allelecall_results(args.output_directory, args.schema_directory)

    # remove temporary files with paths to genomes and schema files
    fu.remove_files([schema_genes, genomes_files])


@dut.process_timer
def evaluate_schema():

    def msg(name=None):
        # simple command to evaluate schema or set of loci
        simple_cmd = ('chewBBACA.py SchemaEvaluator -i <input_files> '
                                                   '-l <output_file> '
                                                   '--cpu <cpu_cores>')

        usage_msg = ('\nEvaluate schema with default parameters:\n  {0}\n'.format(simple_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(prog='SchemaEvaluator',
                                     description='Evaluate the number of alelles and allele size '
                                                 'variation for the loci in a schema or for a set '
                                                 'of selected loci. Provide information about '
                                                 'problematic alleles per locus and individual pages '
                                                 'for each locus with a plot with allele size, a Neighbor '
                                                 'Joining tree based on a multiple sequence alignment (MSA) '
                                                 'and a visualization of the MSA.',
                                     usage=msg(),
                                     formatter_class=ModifiedHelpFormatter)

    parser.add_argument('SchemaEvaluator', nargs='+',
                        help='Evaluates a set of loci.')

    parser.add_argument('-i', type=str, required=True,
                        dest='input_files',
                        help='Path to the schema\'s directory or path to a file containing '
                             'the paths to the FASTA files of the loci that will be evaluated, '
                             'one per line.')

    parser.add_argument('-l', type=str, required=True,
                        dest='output_file',
                        help='Path to the output HTML file.')

    parser.add_argument('-p', action='store_true', required=False,
                        default=False, dest='conserved',
                        help='If all alleles must be within the threshold for the '
                             'locus to be considered as having low length variability.')

    parser.add_argument('--log', action='store_true', default=False,
                        dest='log_scale',
                        help='Apply log scale transformation to the yaxis '
                             'of the plot with the number of alleles per locus.')

    parser.add_argument('-ta', type=int, required=False,
                        default=11, dest='translation_table',
                        help='Genetic code used to translate coding '
                             'sequences.')

    parser.add_argument('-t', type=float, required=False,
                        default=0.05, dest='threshold',
                        help='Allele size variation threshold. If an allele has '
                             'a size within the interval of the locus mode -/+ '
                             'the threshold, it will be considered a conserved '
                             'allele.')

    parser.add_argument('--title', type=str, required=False,
                        default='My Analyzed wg/cg MLST Schema - Rate My Schema',
                        dest='title',
                        help='Title displayed on the html page.')

    parser.add_argument('--cpu', type=int, required=False,
                        default=1, dest='cpu_cores',
                        help='Number of CPU cores to use to run the process.')

    parser.add_argument('-s', type=int, required=False,
                        default=500, dest='split_range',
                        help='Number of boxplots displayed in the plot area (more than '
                             '500 can lead to performance issues).')

    parser.add_argument('--light', action='store_true', required=False,
                        default=False, dest='light_mode',
                        help='Skip clustal and mafft.')

    args = parser.parse_args()
    del args.SchemaEvaluator

    ValidateSchema.main(**vars(args))


@dut.process_timer
def test_schema():

    def msg(name=None):
        # simple command to evaluate genome quality
        simple_cmd = ('chewBBACA.py TestGenomeQuality -i <input_file> '
                                                   '-n <max_iteration> '
                                                   '-t <max_threshold>'
                                                   '-s <step>')

        usage_msg = ('\nEvaluate genome quality with default parameters:\n  {0}\n'.format(simple_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(description='This process evaluates the quality of genomes '
                                                 'based on the results of the AlleleCall process.',
                                     usage=msg(),
                                     formatter_class=ModifiedHelpFormatter)

    parser.add_argument('TestGenomeQuality', nargs='+',
                        help='Evaluate the quality of input genomes based '
                             'on allele calling results.')

    parser.add_argument('-i', type=str, required=True,
                        dest='input_file',
                        help='Path to file with a matrix of allelic profiles.')

    parser.add_argument('-n', type=int, required=True,
                        dest='max_iteration',
                        help='Maximum number of iterations.')

    parser.add_argument('-t', type=int, required=True,
                        dest='max_threshold',
                        help='Maximum threshold of bad calls above 95 percent.')

    parser.add_argument('-s', type=int, required=True,
                        dest='step',
                        help='Step between each threshold analysis.')

    parser.add_argument('-o', type=str, required=False,
                        default='.', dest='output_directory',
                        help='Path to the output directory that will '
                             'store output files')

    parser.add_argument('-v', '--verbose', action='store_true',
                        default=False, dest='verbose',
                        help='Increase stdout verbosity.')

    args = parser.parse_args()
    del args.TestGenomeQuality

    TestGenomeQuality.main(**vars(args))


@dut.process_timer
def extract_cgmlst():

    def msg(name=None):
        # simple command to determine loci that constitute cgMLST
        simple_cmd = ('  chewBBACA.py ExtractCgMLST -i <input_file> '
                                                   '-o <output_directory> ')

        # command to determine cgMLST with custom threshold
        threshold_cmd = ('  chewBBACA.py ExtractCgMLST -i <input_file> '
                                                   '-o <output_directory> '
                                                   '\n\t\t\t     --p <threshold>')

        # command to get information about a single schema
        remove_cmd = ('  chewBBACA.py ExtractCgMLST -i <input_file> '
                                                   '-o <output_directory> '
                                                   '\n\t\t\t     --r <genes2remove> '
                                                   '--g <genomes2remove>')

        usage_msg = ('\nDetermine cgMLST:\n{0}\n'
                     '\nDetermine cgMLST based on non-default threshold:\n{1}\n'
                     '\nRemove genes and genomes from matrix:\n{2}\n'
                     ''.format(simple_cmd, threshold_cmd, remove_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(prog='ExtractCgMLST',
                                     description='Determines the set of '
                                                 'loci that constitute the '
                                                 'core genome based on a '
                                                 'threshold.',
                                     usage=msg(),
                                     formatter_class=ModifiedHelpFormatter)

    parser.add_argument('ExtractCgMLST', nargs='+',
                        help='Determines the set of '
                             'loci that constitute the '
                             'core genome based on a '
                             'threshold.')

    parser.add_argument('-i', type=str, required=True,
                        dest='input_file',
                        help='Path to input file containing a matrix with '
                             'allelic profiles.')

    parser.add_argument('-o', type=str, required=True,
                        dest='output_directory',
                        help='Path to the directory where the process '
                             'will store output files.')

    parser.add_argument('--p', '-p', type=float, required=False,
                        default=1, dest='threshold',
                        help='Genes that constitute the core genome '
                             'must be in a proportion of genomes that is '
                             'at least equal to this value.')

    parser.add_argument('--r', '-r', type=str, required=False,
                        default=False, dest='genes2remove',
                        help='Path to file with a list of genes/columns to '
                             'remove from the matrix (one gene identifier '
                             'per line).')

    parser.add_argument('--g', '-g', type=str, required=False,
                        default=False, dest='genomes2remove',
                        help='Path to file with a list of genomes/rows to '
                             'remove from the matrix (one genome identifier '
                             'per line).')

    args = parser.parse_args()
    del args.ExtractCgMLST

    Extract_cgAlleles.main(**vars(args))


@dut.process_timer
def remove_genes():

    def msg(name=None):

        # simple command to remove a set of genes from a matrix with allelic profiles
        simple_cmd = ('  chewBBACA.py RemoveGenes -i <input_file> '
                                                   '-g <genes_list> '
                                                   '-o <output_file>')

        usage_msg = ('\nRemove a set of genes from a matrix with allelic profiles:\n{0}\n'.format(simple_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(description='Remove loci from a matrix with allelic profiles.',
                                     usage=msg())

    parser.add_argument('RemoveGenes', nargs='+',
                        help='Remove loci from a matrix with allelic profiles.')

    parser.add_argument('-i', type=str, required=True,
                        dest='input_file',
                        help='TSV file that contains a matrix with allelic profiles '
                             'determined by the AlleleCall process.')

    parser.add_argument('-g', type=str, required=True,
                        dest='genes_list',
                        help='File with the list of genes to remove.')

    parser.add_argument('-o', type=str, required=True,
                        dest='output_file',
                        help='Path to the output file that will be created with the '
                             'new matrix.')

    parser.add_argument('--inverse', action='store_true', default=False,
                        dest='inverse',
                        help='List of genes that is provided is the list of genes to '
                             'keep and all other genes should be removed.')

    args = parser.parse_args()
    del args.RemoveGenes

    RemoveGenes.main(**vars(args))


@dut.process_timer
def join_profiles():

    def msg(name=None):
        return '''chewBBACA.py JoinProfiles [RemoveGenes ...][-h]
                  -p1 -p2 -o [O]'''

    parser = argparse.ArgumentParser(description='This program joins two '
                                                 'profiles, returning a '
                                                 'single profile file with '
                                                 'the common loci',
                                     usage=msg())

    parser.add_argument('JoinProfiles', nargs='+',
                        help='join profiles')

    parser.add_argument('-p1', nargs='?', type=str, required=True,
                        dest='profile1',
                        help='profile 1')

    parser.add_argument('-p2', nargs='?', type=str, required=True,
                        dest='profile2',
                        help='profile 2')

    parser.add_argument('-o', nargs='?', type=str, required=True,
                        dest='output_file',
                        help='output file name')

    args = parser.parse_args()
    del args.JoinProfiles

    profile_joiner.main(**vars(args))


@dut.process_timer
def prep_schema():

    def msg(name=None):

        # simple command to adapt external schema with default arguments values
        simple_cmd = ('  chewBBACA.py PrepExternalSchema -i <input_files> '
                                                      '-o <output_directory> '
                                                      '--ptf <ptf_path> ')

        # command to adapt external schema with non-default arguments values
        params_cmd = ('  chewBBACA.py PrepExternalSchema -i <input_files> '
                                                      '-o <output_directory> '
                                                      '--ptf <ptf_path>\n'
                                                      '\t\t\t\t  --cpu <cpu_cores> '
                                                      '--bsr <blast_score_ratio> '
                                                      '--l <minimum_length>\n'
                                                      '\t\t\t\t  --t <translation_table> '
                                                      '--st <size_threshold>')

        usage_msg = ('\nAdapt external schema (one FASTA file per schema gene):\n\n{0}\n'
                     '\nAdapt external schema with non-default parameters:\n\n{1}\n'.format(simple_cmd, params_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(prog='PrepExternalSchema',
                                     description='This script enables the '
                                                 'adaptation of external '
                                                 'schemas so that the loci '
                                                 'and alleles present in '
                                                 'those schemas can be used '
                                                 'with chewBBACA. During '
                                                 'the process, alleles that '
                                                 'do not correspond to a '
                                                 'complete CDS or that cannot '
                                                 'be translated are discarded '
                                                 'from the final schema. One '
                                                 'or more alleles of each '
                                                 'gene/locus will be chosen '
                                                 'as representatives and '
                                                 'included in the "short" '
                                                 'directory.',
                                     usage=msg(),
                                     formatter_class=ModifiedHelpFormatter)

    parser.add_argument('PrepExternalSchema', nargs='+',
                        help='Adapt an external schema to be used with '
                        'chewBBACA.')

    parser.add_argument('-i', type=str, required=True, dest='input_files',
                        help='Path to the folder containing the fasta files, '
                             'one fasta file per gene/locus (alternatively, '
                             'a file with a list of paths can be given).')

    parser.add_argument('-o', type=str, required=True, dest='output_directory',
                        help='The directory where the output files will be '
                             'saved (will create the directory if it does not '
                             'exist).')

    parser.add_argument('--ptf', type=str, required=False,
                        default=False, dest='ptf_path',
                        help='Path to the Prodigal training file that '
                             'will be associated with the adapted schema.')

    parser.add_argument('--bsr', type=pv.bsr_type,
                        required=False, default=0.6, dest='blast_score_ratio',
                        help='The BLAST Score Ratio value that will be '
                             'used to adapt the external schema (default=0.6).')

    parser.add_argument('--l', type=pv.minimum_sequence_length_type,
                        required=False, default=0, dest='minimum_length',
                        help='Minimum sequence length accepted. Sequences with'
                             ' a length value smaller than the value passed to this'
                             ' argument will be discarded (default=0).')

    parser.add_argument('--t', type=pv.translation_table_type,
                        required=False, default=11, dest='translation_table',
                        help='Genetic code to use for CDS translation.'
                             ' (default=11, for Bacteria and Archaea)')

    parser.add_argument('--st', type=pv.size_threshold_type,
                        required=False, default=0.2, dest='size_threshold',
                        help='CDS size variation threshold. At the default '
                             'value of 0.2, alleles with size variation '
                             '+-20 percent when compared to the representative '
                             'will not be included in the final schema.')

    parser.add_argument('--cpu', type=int, required=False,
                        default=1, dest='cpu_cores',
                        help='The number of CPU cores to use (default=1).')

    parser.add_argument('--b', type=pv.check_blast, required=False,
                        default='', dest='blast_path',
                        help='Path to the BLAST executables.')

    args = parser.parse_args()
    del args.PrepExternalSchema

    # check if ptf exists
    if args.ptf_path is not False:
        ptf_val = aux.check_ptf(args.ptf_path)
        if ptf_val[0] is False:
            sys.exit(ptf_val[1])

    PrepExternalSchema.main(**vars(args))

    # copy training file to schema directory
    if args.ptf_path is not False:
        ptf_hash = fu.hash_file(args.ptf_path, 'rb')
        shutil.copy(args.ptf_path, args.output_directory)
    else:
        ptf_hash = ''

    # write schema config file
    schema_config = aux.write_schema_config(args.blast_score_ratio, ptf_hash,
                                            args.translation_table, args.minimum_length,
                                            version, args.size_threshold, None,
                                            None, None, None, args.output_directory)

    # create hidden file with genes/loci list
    genes_list_file = aux.write_gene_list(args.output_directory)


@dut.process_timer
def find_uniprot():

    def msg(name=None):

        # simple command to determine annotations for the loci in a schema
        simple_cmd = ('  chewBBACA.py UniprotFinder -i <input_files> '
                                                   '-t <protein_table> '
                                                   '--cpu <cpu_cores>')

        usage_msg = ('\nFind annotations for loci in a schema:\n\n{0}\n'.format(simple_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(prog='UniprotFinder',
                                     description='This process determines loci annotations based '
                                                 'on exact matches found in the UniProt database.',
                                     usage=msg(),
                                     formatter_class=ModifiedHelpFormatter)

    parser.add_argument('UniprotFinder', nargs='+',
                        help='Determine annotations for loci in a schema.')

    parser.add_argument('-i', type=str, required=True,
                        dest='input_files',
                        help='Path to the schema\'s directory or to a file with '
                             'a list of paths to loci FASTA files, one per line.')

    parser.add_argument('-t', type=str, required=True,
                        dest='protein_table',
                        help='Path to the "proteinID_Genome.tsv" file created by '
                             'the CreateSchema process.')

    parser.add_argument('--cpu', type=int, required=False,
                        default=1, dest='cpu_cores',
                        help='The number of CPU cores to use during the process.')

    args = parser.parse_args()
    del args.UniprotFinder

    uniprot_find.main(**vars(args))


@dut.process_timer
def download_schema():

    def msg(name=None):
        # simple command to download a schema from the NS
        simple_cmd = ('  chewBBACA.py DownloadSchema -sp <species_id> '
                                                  '-sc <schema_id> '
                                                  '-o <download_folder> ')

        # command to download a schema from the NS with non-default arguments values
        params_cmd = ('  chewBBACA.py DownloadSchema -sp <species_id> '
                                                  '-sc <schema_id> '
                                                  '-o <download_folder>\n'
                                                  '\t\t\t      --cpu <cpu_cores> '
                                                  '--ns <nomenclature_server_url> ')

        usage_msg = ('\nDownload schema:\n{0}\n'
                     '\nDownload schema with non-default parameters:\n{1}\n'.format(simple_cmd, params_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(prog='DownloadSchema',
                                     description='This program downloads '
                                                 'a schema from the NS.',
                                     usage=msg(),
                                     formatter_class=ModifiedHelpFormatter)

    parser.add_argument('DownloadSchema', nargs='+',
                        help='This program downloads a schema from '
                             'the NS.')

    parser.add_argument('-sp', type=str, required=True,
                        dest='species_id',
                        help='The integer identifier or name of the species '
                             'that the schema is associated to in the NS.')

    parser.add_argument('-sc', type=str, required=True,
                        dest='schema_id',
                        help='The URI, integer identifier or name of '
                             'the schema to download from the NS.')

    parser.add_argument('-o', type=str, required=True,
                        dest='download_folder',
                        help='Output folder to which the schema will '
                             'be saved.')

    parser.add_argument('--cpu', type=int, required=False,
                        default=1, dest='cpu_cores',
                        help='Number of CPU cores that will '
                             'be passed to the PrepExternalSchema process to '
                             'determine representatives and create the '
                             'final schema.')

    parser.add_argument('--ns', type=pv.validate_ns_url, required=False,
                        default='main',
                        dest='nomenclature_server',
                        help='The base URL for the Nomenclature Server. '
                             'The default value, "main", will establish a '
                             'connection to "https://chewbbaca.online/", '
                             '"tutorial" to "https://tutorial.chewbbaca.online/" '
                             'and "local" to "http://127.0.0.1:5000/NS/api/" (localhost). '
                             'Users may also provide the IP address to other '
                             'Chewie-NS instances.')

    parser.add_argument('--d', type=str, required=False,
                        default=None,
                        dest='date',
                        help='Download schema with state from specified date. '
                             'Must be in the format "Y-m-dTH:M:S".')

    parser.add_argument('--latest', required=False, action='store_true',
                        dest='latest',
                        help='If the compressed version that is available is '
                             'not the latest, downloads all loci and constructs '
                             'schema locally.')

    parser.add_argument('--b', type=pv.check_blast, required=False,
                        default='', dest='blast_path',
                        help='Path to the BLAST executables.')

    args = parser.parse_args()
    del args.DownloadSchema

    down_schema.main(**vars(args))


@dut.process_timer
def upload_schema():

    def msg(name=None):
        # simple command to load a schema to the NS
        simple_cmd = ('  chewBBACA.py LoadSchema -i <schema_directory> '
                                              '-sp <species_id> '
                                              '-sn <schema_name>\n'
                                              '\t\t\t  -lp <loci_prefix> ')

        # command to load a schema to the NS with non-default arguments values
        params_cmd = ('  chewBBACA.py LoadSchema -i <schema_directory> '
                                              '-sp <species_id> '
                                              '-sn <schema_name>\n'
                                              '\t\t\t  -lp <loci_prefix> '
                                              '--thr <threads> '
                                              '--ns <nomenclature_server_url>')

        # command to continue schema upload that was interrupted or aborted
        continue_cmd = ('  chewBBACA.py LoadSchema -i <schema_directory> '
                                                '-sp <species_id> '
                                                '-sn <schema_name>\n'
                                                '\t\t\t  --continue_up')

        usage_msg = ('\nLoad schema:\n{0}\n'
                     '\nLoad schema with non-default parameters:\n{1}\n'
                     '\nContinue schema upload that was interrupted or aborted:\n{2}\n'.format(simple_cmd, params_cmd, continue_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(prog='LoadSchema',
                                     description='This program uploads '
                                                 'a schema to the NS.',
                                     usage=msg(),
                                     formatter_class=ModifiedHelpFormatter)

    parser.add_argument('LoadSchema', nargs='+',
                        help='This program loads a schema to '
                             'the NS.')

    parser.add_argument('-i', type=str, required=True,
                        dest='schema_directory',
                        help='Path to the directory of the schema to upload.')

    parser.add_argument('-sp', type=str, required=True,
                        dest='species_id',
                        help='The integer identifier or name of the species '
                             'that the schema will be associated to in '
                             'the NS.')

    parser.add_argument('-sn', type=str, required=True,
                        dest='schema_name',
                        help='A brief and meaningful name that '
                             'should help understand the type and content '
                             'of the schema.')

    parser.add_argument('-lp', type=str, required=True,
                        dest='loci_prefix',
                        help='Prefix included in the name of each locus of '
                             'the schema.')

    parser.add_argument('--df', type=str, required=False,
                        dest='description_file', default=None,
                        help='Path to a text file with a description '
                             'about the schema. Markdown syntax is supported '
                             'in order to offer greater customizability of '
                             'the rendered description in the Frontend. '
                             'Will default to the schema\'s name if the user '
                             'does not provide a valid path for a file.')

    parser.add_argument('--a', type=str, required=False,
                        dest='annotations', default=None,
                        help='Path to a TSV file with loci annotations. '
                             'The first column has loci identifiers '
                             '(w/o .fasta extension), the second has user '
                             'annotations and the third has custom '
                             'annotations.')

    parser.add_argument('--cpu', type=int, required=False,
                        dest='cpu_cores', default=1,
                        help='Number of CPU cores that will '
                             'be used in the Schema Pre-processing step.')

    parser.add_argument('--thr', type=int, required=False,
                        default=20, dest='threads',
                        help='Number of threads to use to search for '
                             'annotations on UniProt')

    parser.add_argument('--ns', type=pv.validate_ns_url, required=False,
                        default='main',
                        dest='nomenclature_server',
                        help='The base URL for the Nomenclature Server. '
                             'The default value, "main", will establish a '
                             'connection to "https://chewbbaca.online/", '
                             '"tutorial" to "https://tutorial.chewbbaca.online/" '
                             'and "local" to "http://127.0.0.1:5000/NS/api/" (localhost). '
                             'Users may also provide the IP address to other '
                             'Chewie-NS instances.')

    parser.add_argument('--continue_up', required=False, action='store_true',
                        dest='continue_up',
                        help='If the process should check if the schema '
                             'upload was interrupted and try to finish it.')

    args = parser.parse_args()
    del args.LoadSchema

    load_schema.main(**vars(args))


@dut.process_timer
def synchronize_schema():

    def msg(name=None):
        # simple command to synchronize a schema with its NS version
        simple_cmd = ('  chewBBACA.py SyncSchema -sc <schema_directory> ')

        # command to synchronize a schema with its NS version with non-default arguments values
        params_cmd = ('  chewBBACA.py SyncSchema -sc <schema_directory> '
                                                '--cpu <cpu_cores> '
                                                '--ns <nomenclature_server_url>')

        # command to submit novel local alleles
        submit_cmd = ('  chewBBACA.py SyncSchema -sc <schema_directory> --submit')

        usage_msg = ('\nSync schema:\n{0}\n'
                     '\nSync schema with non-default parameters:\n{1}\n'
                     '\nSync schema and send novel local alleles to the NS:\n{2}\n'.format(simple_cmd, params_cmd, submit_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(prog='SyncSchema',
                                     description='This program syncs a local '
                                                 'schema with NS',
                                     usage=msg(),
                                     formatter_class=ModifiedHelpFormatter)

    parser.add_argument('SyncSchema', nargs='+',
                        help='Synchronize a local schema, previously '
                             'downloaded from the NS, with its latest '
                             'version in the NS.')

    parser.add_argument('-sc', type=str, required=True,
                        dest='schema_directory',
                        help='Path to the directory with the schema to be'
                             'synced.')

    parser.add_argument('--cpu', type=int, required=False,
                        default=1, dest='cpu_cores',
                        help='Number of CPU cores that will '
                             'be used to determine new representatives '
                             'if the process downloads new alleles from '
                             'the Chewie-NS.')

    parser.add_argument('--ns', type=pv.validate_ns_url, required=False,
                        default=None,
                        dest='nomenclature_server',
                        help='The base URL for the Nomenclature Server. '
                             'The default option will get the base URL from the '
                             'schema\'s URI. It is also possible to specify other '
                             'options that are available in chewBBACA\'s configs, '
                             'such as: "main" will establish a connection to '
                             '"https://chewbbaca.online/", "tutorial" to '
                             '"https://tutorial.chewbbaca.online/" and "local" '
                             'to "http://127.0.0.1:5000/NS/api/" (localhost). '
                             'Users may also provide the IP address to other '
                             'Chewie-NS instances.')

    parser.add_argument('--submit', required=False,
                        action='store_true', dest='submit',
                        help='If the process should identify new alleles '
                             'in the local schema and send them to the '
                             'NS. (only users with permissons level of '
                             'Contributor can submit new alleles).')

    parser.add_argument('--b', type=pv.check_blast, required=False,
                        default='', dest='blast_path',
                        help='Path to the BLAST executables.')

    args = parser.parse_args()
    del args.SyncSchema

    sync_schema.main(**vars(args))


@dut.process_timer
def ns_stats():

    def msg(name=None):
        # simple command to list species and totals
        simple_cmd = ('  chewBBACA.py NSStats -m species ')

        # command to list all schemas for a species
        schemas_cmd = ('  chewBBACA.py NSStats -m schemas --sp <species_id> ')

        # command to get information about a single schema
        schema_cmd = ('  chewBBACA.py NSStats -m schemas --sp <species_id> '
                                             '--sc <schema_id>')

        usage_msg = ('\nList species and totals:\n{0}\n'
                     '\nList all schemas for a species and associated information:\n{1}\n'
                     '\nGet information about a particular schema:\n{2}\n'
                     ''.format(simple_cmd, schemas_cmd, schema_cmd))

        return usage_msg

    parser = argparse.ArgumentParser(prog='NSStats',
                                     description='Retrieve basic information '
                                                 'about the species and schemas in '
                                                 'the Chewie-NS.',
                                     usage=msg(),
                                     formatter_class=ModifiedHelpFormatter)

    parser.add_argument('NSStats', nargs='+',
                        help='')

    parser.add_argument('-m', type=str, required=True,
                        dest='mode', choices=['species', 'schemas'],
                        help='The process can retrieve the list of species '
                             '("species" option) in the Chewie-NS or the '
                             'list of schemas for a species '
                             '("schemas" option).')

    parser.add_argument('--ns', type=pv.validate_ns_url, required=False,
                        default='main',
                        dest='nomenclature_server',
                        help='The base URL for the Nomenclature Server. '
                             'The default value, "main", will establish a '
                             'connection to "https://chewbbaca.online/", '
                             '"tutorial" to "https://tutorial.chewbbaca.online/" '
                             'and "local" to "http://127.0.0.1:5000/NS/api/" (localhost). '
                             'Users may also provide the IP address to other '
                             'Chewie-NS instances.')

    parser.add_argument('--sp', type=str, required=False,
                        dest='species_id', default=None,
                        help='The integer identifier of a '
                             'species in the Chewie-NS.')

    parser.add_argument('--sc', type=str, required=False,
                        dest='schema_id', default=None,
                        help='The integer identifier of a schema in '
                             'the Chewie-NS.')

    args = parser.parse_args()
    del args.NSStats

    stats_requests.main(**vars(args))


def main():

    functions_info = {'CreateSchema': ['Create a gene-by-gene schema based on '
                                       'a set of input genomes.',
                                       create_schema],
                      'AlleleCall': ['Determine the allelic profiles of a set of '
                                     'input genomes based on a schema.',
                                     allele_call],
                      'SchemaEvaluator': ['Tool that builds an html output '
                                          'to better navigate/visualize '
                                          'your schema.',
                                          evaluate_schema],
                      'TestGenomeQuality': ['Analyze your allele call output '
                                            'to refine schemas.',
                                            test_schema],
                      'ExtractCgMLST': ['Determines the set of '
                                        'loci that constitute the '
                                        'core genome based on a '
                                        'threshold.',
                                        extract_cgmlst],
                      'RemoveGenes': ['Remove a provided list of loci from '
                                      'your allele call output.',
                                      remove_genes],
                      'PrepExternalSchema': ['Adapt an external schema to be '
                                             'used with chewBBACA.',
                                             prep_schema],
                      'JoinProfiles': ['Join two profiles in a single profile '
                                       'file.',
                                       join_profiles],
                      'UniprotFinder': ['Retrieve annotations for loci in a schema.',
                                        find_uniprot],
                      'DownloadSchema': ['Download a schema from the Chewie-NS.',
                                         download_schema],
                      'LoadSchema': ['Upload a schema to the Chewie-NS.',
                                     upload_schema],
                      'SyncSchema': ['Synchronize a schema with its remote version '
                                     'in the Chewie-NS.',
                                     synchronize_schema],
                      'NSStats': ['Retrieve basic information about the species '
                                  'and schemas in the Chewie-NS.',
                                  ns_stats]}

    print('\nchewBBACA version: {0}'.format(version))
    print('Authors: {0}'.format(cnst.authors))
    print('Github: {0}'.format(cnst.repository))
    print('Wiki: {0}'.format(cnst.wiki))
    print('Tutorial: {0}'.format(cnst.tutorial))
    print('Contacts: {0}\n'.format(cnst.contacts))

    matches = ["version", "v"]
    if len(sys.argv) > 1 and any(m in sys.argv[1] for m in matches):
        print(version)
        sys.exit(0)

    # display help message if selected process is not valid
    if len(sys.argv) == 1 or sys.argv[1] not in functions_info:
        print('\n\tUSAGE: chewBBACA.py [module] -h \n')
        print('Select one of the following functions :\n')
        for f in functions_info:
            print('{0}: {1}'.format(f, functions_info[f][0]))
        sys.exit(0)

    # Check python version
    python_version = pv.validate_python_version()

    process = sys.argv[1]
    functions_info[process][1]()


if __name__ == "__main__":

    main()
