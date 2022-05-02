#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Purpose
-------
This module enables

Expected input
--------------

The process expects the following variables whether through command line
execution or invocation of the :py:func:`main` function:

- ``-i``, ``input_files`` : Path to the directory that contains the input
  FASTA files. Alternatively, a single file with a list of paths to FASTA
  files, one per line.

    - e.g.: ``/home/user/genomes``

- ``-o``, ``output_directory`` : Output directory where the process will
  store intermediate files and create the schema's directory.

    - e.g.: ``/home/user/schemas/new_schema``

- ``--ptf``, ``ptf_path`` : Path to the Prodigal training file.

    - e.g.: ``/home/user/training_files/species.trn``

- ``--bsr``, ``blast_score_ratio`` : BLAST Score Ratio value.

    - e.g.: ``0.6``

- ``--l``, ``minimum_length`` : Minimum sequence length. Coding sequences
  shorter than this value are excluded.

    - e.g.: ``201``

- ``--t``, ``translation_table`` : Genetic code used to predict genes and
  to translate coding sequences.

    - e.g.: ``11``

- ``--st``, ``size_threshold`` : CDS size variation threshold. Added to the
  schema's config file and used to identify alleles with a length value that
  deviates from the locus length mode during the allele calling process.

    - e.g.: ``0.2``

- ``--w``, ``word_size`` : word size used to generate k-mers during the
  clustering step.

    - e.g.: ``5``

- ``--ws``, ``window_size`` : window size value. Number of consecutive
  k-mers included in each window to determine a minimizer.

    - e.g.: ``5``

- ``--cs``, ``clustering_sim`` : clustering similarity threshold. Minimum
  decimal proportion of shared distinct minimizers for a sequence to be
  added to a cluster.

    - e.g.: ``0.2``

- ``--cpu``, ``cpu_cores`` : Number of CPU cores used to run the process.

    - e.g.: ``4``

- ``--b``, ``blast_path`` : Path to the BLAST executables.

    - e.g.: ``/home/software/blast``

- ``--pm``, ``prodigal_mode`` : Prodigal running mode.

    - e.g.: ``single``

- ``--CDS``, ``cds_input`` : If provided, input is a single or several FASTA
  files with coding sequences (skips gene prediction and CDS extraction).

    - e.g.: ``/home/user/coding_sequences_files``

- ``--no-cleanup``, ``no_cleanup`` : If provided, intermediate files
  generated during process execution are not removed at the end.

Code documentation
------------------
"""


import os
import csv
import sys
import argparse
from collections import Counter

from Bio import SeqIO

try:
    from utils import (constants as ct,
                       blast_wrapper as bw,
                       core_functions as cf,
                       file_operations as fo,
                       fasta_operations as fao,
                       process_datetime as pdt,
                       sequence_manipulation as sm,
                       iterables_manipulation as im,
                       multiprocessing_operations as mo)
except:
    from CHEWBBACA.utils import (constants as ct,
                                 blast_wrapper as bw,
                                 core_functions as cf,
                                 file_operations as fo,
                                 fasta_operations as fao,
                                 process_datetime as pdt,
                                 sequence_manipulation as sm,
                                 iterables_manipulation as im,
                                 multiprocessing_operations as mo)


# import module to determine variable size
import get_varSize_deep as gs


def create_classification_file(locus_id, output_directory, locus_results):
    """ Uses the Pickle module to create a file with an empty
        directory that can be later modified to store
        classification results.

    Parameters
    ----------
    locus_id : str
        The identifier of the locus.
    output_directory : str
        Path to the output directory where the file will
        be created.
    locus_results : dict
        Results to save to file.

    Return
    ------
    pickle_out : str
        Path to the file created to store classification
        results.
    """

    pickle_out = fo.join_paths(output_directory,
                               [locus_id+'_results'])

    # create file with empty results structure
    fo.pickle_dumper(locus_results, pickle_out)

    return pickle_out


def update_classification(genome_id, locus_results, match_info):
    """ Update locus classification for an input.

    Parameters
    ----------
    genome_id : int
        Integer identifier attributed to the input.
    locus_results : dict
        Dictionary with the matches found for the locus
        in the inputs.
    match_info : list
        List with information about the match found for
        the locus.

    Returns
    -------
    locus_results : dict
        Updated results.
    """

    # add data about match
    locus_results.setdefault(genome_id, [match_info[3]]).append(match_info)

    # get all classifications
    classes_list = [c[3] for c in locus_results[genome_id][1:]]
    # evaluate classification for genomes with multiple matches
    if len(classes_list) > 1:
        classes_counts = Counter(classes_list)
        # multiple matches, single class
        if len(classes_counts) == 1:
            if 'EXC' in classes_counts:
                locus_results[genome_id][0] = 'NIPHEM'
            # multiple INF, ASM, ALM, etc classes are classified as NIPH
            else:
                locus_results[genome_id][0] = 'NIPH'
        # multiple matches and classes
        elif len(classes_counts) > 1:
            # mix of classes that include both EXC and INF are classified as NIPH
            if 'EXC' and 'INF' in classes_counts:
                locus_results[genome_id][0] = 'NIPH'
            # any class with PLOT3, PLOT5 or LOTSC are classified as NIPH
            elif any([c in ['PLOT3', 'PLOT5', 'LOTSC'] for c in classes_counts]) is True:
                locus_results[genome_id][0] = 'NIPH'
            # EXC or INF with ASM/ALM
            elif 'EXC' in classes_counts or 'INF' in classes_counts:
                match_count = classes_counts.get('EXC', classes_counts['INF'])
                # Single EXC or INF classified as EXC or INF even if there are ASM/ALM
                if match_count == 1:
                    locus_results[genome_id][0] = 'EXC' if 'EXC' in classes_counts else 'INF'
                # multiple EXC or INF classified as NIPH
                else:
                    locus_results[genome_id][0] = 'NIPH'
            # multiple ASM and ALM are classified as NIPH
            else:
                locus_results[genome_id][0] = 'NIPH'

    return locus_results


def count_classifications(classification_files):
    """ Determines the global counts for each classification
        type except LNF for a set of loci.

    Parameters
    ----------
    classification files : list
        List of paths to pickled files that contain the
        classifications for a set of loci.

    Returns
    -------
    global_counts : dict
        Dicitonary with classification types as keys
        and the total number of inputs classified per
        type as values.
    total_cds : int
        The total number of coding sequences that
        have been classified.
    """

    classification_counts = Counter()
    # get total number of classified CDSs
    total_cds = 0
    for file in classification_files:
        locus_results = fo.pickle_loader(file)
        total_cds += sum([len([r for r in c if type(r) == tuple])
                          for g, c in locus_results.items()])
        locus_classifications = [c[0] for g, c in locus_results.items()]
        locus_counts = Counter(locus_classifications)
        classification_counts += locus_counts

    # add classification that might be missing
    classification_counts.update(Counter({k: 0 for k in ct.ALLELECALL_CLASSIFICATIONS[:-1]
                                          if k not in classification_counts}))

    return [classification_counts, total_cds]


def dna_exact_matches(locus_file, presence_DNAhashtable, locus_classifications, input_ids):
    """ Finds exact matches between DNA sequences extracted from inputs
        and the alleles for a locus in the schema.

    Parameters
    ----------
    locus_file : str
        Path to the locus FASTA file that contains the locus
        alleles.
    presence_DNAhashtable : dict
        Dictionary with SHA-256 hashes for distinct DNA
        sequences extracted from the inputs and lists of
        genome integer identifiers enconded with the
        polyline algorithm as values.
    locus_classifications : str
        Dictionary with the matches found for the locus
        in the inputs.
    input_ids : dict
        Dictionary with input integer identifiers as keys
        and input sequence identifiers as values.

    Returns
    -------
    locus_classifications : dict
        Updated results with the exact matches found for the
        locus.
    matched_seqids : list
        Sequence identifiers of the distinct CDSs that were
        matched.
    total_matches : int
        Number of exact matches.
    """

    # read Fasta records
    locus_alleles = fao.import_sequences(locus_file)
    # determine SHA-256 hash for locus sequences
    allele_hashes = {seqid: im.hash_sequence(sequence)
                     for seqid, sequence in locus_alleles.items()}

    # determine locus alleles that are in inputs
    exact_matches = {seqid.split('_')[-1]: seq_hash
                     for seqid, seq_hash in allele_hashes.items()
                     if seq_hash in presence_DNAhashtable}

    matched_seqids = []
    total_matches = 0
    for seqid, seq_hash in exact_matches.items():
        # decode list of inputs that contain allele
        matched_inputs = im.polyline_decoding(presence_DNAhashtable[seq_hash])
        # seqid chosen as repsentative during sequence deduplication
        representative_seqid = '{0}-protein{1}'.format(input_ids[matched_inputs[1]], matched_inputs[0])
        match_data = (seqid, representative_seqid, seq_hash, 'EXC', 1.0)
        # classify as exact matches
        # skip first value, it is the protein id
        for gid in matched_inputs[1:]:
            locus_classifications = update_classification(gid, locus_classifications,
                                                          match_data)

        total_matches += len(matched_inputs[1:])
        # store representative id for the sequences
        matched_seqids.append(representative_seqid)

    return [locus_classifications, matched_seqids, total_matches]


def protein_exact_matches(locus_file, presence_PROThashtable,
                          presence_DNAhashtable, locus_classifications,
                          dna_index, input_ids):
    """ Finds exact matches between translated CDSs extracted from inputs
        and the translated alleles for a locus in the schema.

    Parameters
    ----------
    locus_file : str
        Path to the locus FASTA file that contains the locus
        translated alleles.
    presence_PROThashtable : dict
        Dictionary with SHA-256 hashes for distinct protein
        sequences extracted from the inputs and lists of
        sequence identifiers enconded with the polyline
        algorithm as values.
    presence_DNAhashtable : dict
        Dictionary with SHA-256 hashes for distinct DNA
        sequences extracted from the inputs and lists of
        genome integer identifiers enconded with the
        polyline algorithm as values.
    locus_classifications : dict
        Dictionary with the matches found for the locus
        in the inputs.
    dna_index : Bio.File._IndexedSeqFileDict
        Fasta file index created with BioPython.
    input_ids : dict
        Dictionary with input integer identifiers as keys
        and input sequence identifiers as values.

    Returns
    -------
    locus_classifications : dict
        Updated results with the exact matches found for the
        locus.
    exact_prot_hashes : list
        Sequence identifiers of the distinct CDSs that
        were matched.
    total_prots : int
        Number of matched distinct CDSs.
    total_cds : int
        Number of matched CDSs.
    total_distinct_prots : int
        Number of matched distinct prots.
    """

    # read Fasta records
    locus_proteins = fao.import_sequences(locus_file)

    # determine SHA-256 hash for locus sequences
    protein_hashes = {seqid: im.hash_sequence(seq)
                       for seqid, seq in locus_proteins.items()}

    # determine locus alleles that are in inputs
    exact_matches = {seqid.split('_')[-1]: prot_hash
                     for seqid, prot_hash in protein_hashes.items()
                     if prot_hash in presence_PROThashtable}

    total_cds = 0
    total_prots = 0
    total_distinct_prots = 0
    matched_dna = {}
    matched_proteins = set()
    exact_prot_hashes = []
    for protid, prot_hash in exact_matches.items():
        # different alleles might code for the same protein
        # do not proceed if distinct protein sequence has already been seen
        if prot_hash in presence_PROThashtable and prot_hash not in matched_proteins:
            # get protids for distinct DNA CDSs
            matched_protids = im.polyline_decoding(presence_PROThashtable[prot_hash])
            matched_protids = ['{0}-protein{1}'.format(input_ids[matched_protids[i]], matched_protids[i+1])
                               for i in range(0, len(matched_protids), 2)]
            total_prots += len(matched_protids)
            exact_prot_hashes.extend(matched_protids)
            total_distinct_prots += 1
            # for each distinct CDS that codes for the protein
            for m in matched_protids:
                cds = str(dna_index.get(m).seq)
                cds_hash = im.hash_sequence(cds)
                # get IDs of genomes that contain the CDS
                matched_inputs = im.polyline_decoding(presence_DNAhashtable[cds_hash])
                total_cds += len(matched_inputs)-1
                # for each genome ID that contains the CDS
                for gid in matched_inputs[1:]:
                    # first time seeing CDS
                    if cds_hash not in matched_dna:
                        # need to add inferred to locus mode values???
                        current_class = 'INF'
                        representative_seqid = protid
                        matched_dna[cds_hash] = m
                    else:
                        current_class = 'EXC'
                        # if it matches a INF, change protid to seqid of INF
                        # that will be assigned a new allele id later
                        representative_seqid = matched_dna[cds_hash]
                    # for protein exact matches, the seqid of the translated allele,
                    # the seqid of the protein chosen as representative during sequence deduplication,
                    match_data = (protid, m, cds_hash, current_class, 1.0)
                    locus_classifications = update_classification(gid, locus_classifications,
                                                                  match_data)

            matched_proteins.add(prot_hash)

    return [locus_classifications, exact_prot_hashes, total_prots,
            total_cds, total_distinct_prots]


def contig_position_classification(representative_length, representative_leftmost_pos,
                                   representative_rightmost_pos, contig_length,
                                   contig_leftmost_pos, contig_rightmost_pos):
    """ Determines classification based on the position of the
        aligned representative allele in the input contig.

    Parameters
    ----------
    representative_length : int
        Length of the representative allele that matched a
        coding sequence identified in the input contig.
    representative_leftmost_pos : int
        Representative sequence leftmost aligned position.
    representative_rightmost_pos : int
        Representative sequence rightmost aligned position.
    contig_length : int
        Length of the contig that contains the coding sequence
        that matched with the representative allele.
    contig_leftmost_pos : int
        Contig leftmost aligned position.
    contig_rightmost_pos : int
        Contig rightmost aligned position.

    Returns
    -------
    'LOTSC' if the contig is smaller than the matched representative
    allele, 'PLOT5' or 'PLOT3' if the matched allele unaligned part
    exceeds one of the contig ends, None otherwise.
    """

    # check if it is LOTSC because the contig is smaller than matched allele
    if contig_length < representative_length:
        return 'LOTSC'

    # check if it is PLOT
    # match in sense strand
    if contig_rightmost_pos > contig_leftmost_pos:
        # determine rightmost aligned position in contig
        contig_rightmost_rest = contig_length - contig_rightmost_pos
        # determine leftmost aligned position in contig
        contig_leftmost_rest = contig_leftmost_pos
        # determine number of rightmost bases in the target that did not align
        representative_rightmost_rest = representative_length - representative_rightmost_pos
        # determine number of leftmost bases in the target that did not align 
        representative_leftmost_rest = representative_leftmost_pos
    # reverse values because CDS was identified in reverse strand
    elif contig_rightmost_pos < contig_leftmost_pos:
        contig_leftmost_rest = contig_rightmost_pos
        contig_rightmost_rest = contig_length - contig_leftmost_pos
        # also need to reverse values for representative
        representative_leftmost_rest = representative_rightmost_pos
        representative_rightmost_rest = representative_length - representative_leftmost_pos

    # check if the unaligned region of the matched allele exceeds
    # one of the contig ends
    if contig_leftmost_rest < representative_leftmost_rest:
        return 'PLOT5'
    elif contig_rightmost_rest < representative_rightmost_rest:
        return 'PLOT3'


def allele_size_classification(sequence_length, locus_mode, size_threshold):
    """ Determines if the size of a sequence deviates from the locus
        mode based on a sequence size variation threshold.

    Parameters
    ----------
    sequence_length : int
        Length of the DNA sequence.
    locus_mode : int
        Locus allele size mode.
    size_threshold : float
        Sequence size variation threshold.

    Returns
    -------
    'ASM' if sequence size value is below computed sequence
    size interval, 'ALM' if it is above and None if it is
    contained in the interval.
    """

    if sequence_length < (locus_mode[0]-(locus_mode[0])*size_threshold):
        return 'ASM'
    elif sequence_length > (locus_mode[0]+(locus_mode[0])*size_threshold):
        return 'ALM'


def write_loci_summary(classification_files, output_directory, total_inputs):
    """ Writes a TSV file with classification counts and total
        number of classified coding sequences per locus.

    Parameters
    ----------
    classification_files : dict
        Dictionary with the paths to loci FASTA files as keys
        and paths to loci classification files as values.
    output_directory : str
        Path to the output directory where the TSV file will
        be created.
    total_inputs : int
        Total number of inputs.
    """

    loci_stats = [ct.LOCI_STATS_HEADER]
    for k, v in classification_files.items():
        locus_id = fo.get_locus_id(k)
        if locus_id is None:
            locus_id = fo.file_basename(v).split('_results')[0]
        locus_results = fo.pickle_loader(v)

        # count locus classifications
        current_counts = count_classifications([v])
        counts_list = [locus_id]
        for c in ct.ALLELECALL_CLASSIFICATIONS[:-1]:
            counts_list.append(str(current_counts[0][c]))
        # add LNF count
        counts_list.append(str(total_inputs-len(locus_results)))
        counts_list.append(str(current_counts[1]))
        locus_line = im.join_list(counts_list, '\t')
        loci_stats.append(locus_line)

    output_file = fo.join_paths(output_directory, [ct.LOCI_STATS_FILENAME])
    fo.write_lines(loci_stats, output_file)


def write_logfile(start_time, end_time, total_inputs,
                  total_loci, cpu_cores, blast_score_ratio,
                  output_directory):
    """ Writes the log file.

    Parameters
    ----------
    start_time : datetime.datetime
        Datetime object with the date and hour
        determined when the process started running.
    end_time : datetime.datetime
        Datetime object with the date and hour
        determined when the process concluded.
    total_inputs : int
        Number of inputs passed to the process.
    cpu_cores : int
        Number of CPU cores/threads used by the
        process.
    blast_score_ratio : float
        BLAST Score Ratio value used by the
        process.
    output_directory : str
        Path to the output directory where the
        log file will be created.

    Returns
    -------
    log_outfile : str
        Path to the log file.
    """

    start_time_str = pdt.datetime_str(start_time,
                                      date_format='%H:%M:%S-%d/%m/%Y')

    end_time_str = pdt.datetime_str(end_time,
                                    date_format='%H:%M:%S-%d/%m/%Y')

    log_outfile = fo.join_paths(output_directory, [ct.LOGFILE_BASENAME])
    logfile_text = ct.LOGFILE_TEMPLATE.format(start_time_str, end_time_str,
                                              total_inputs,total_loci,
                                              cpu_cores, blast_score_ratio)

    fo.write_to_file(logfile_text, log_outfile, 'w', '')

    return log_outfile


def write_results_alleles(classification_files, input_identifiers,
                          output_directory):
    """ Writes a TSV file with the allelic profiles for the
        input samples.

    Parameters
    ----------
    classification_files : list
        List with the paths to loci classification files.
    input_identifiers : list
        Sorted list that contains input string identifiers.
    output_directory : str
        Path to the output directory.
    """

    # add first column with input identifiers
    columns = [['FILE'] + input_identifiers]
    for file in classification_files:
        # get locus identifier to add as column header
        locus_id = fo.get_locus_id(file)
        if locus_id is None:
            locus_id = fo.file_basename(file).split('_results')[0]
        locus_results = fo.pickle_loader(file)
        locus_column = [locus_id]
        for i in range(1, len(input_identifiers)+1):
            # determine if locus was found in each input
            if i in locus_results:
                current_result = locus_results[i]
                # exact or inferred, append assigned allele id
                if current_result[0] in ['EXC', 'INF']:
                    locus_column.append(current_result[-1])
                # missing data (PLOT, ASM, ALM, ...)
                else:
                    locus_column.append(current_result[0])
            # locus was not identified in the input
            else:
                locus_column.append('LNF')

        columns.append(locus_column)

    # group elements with same list index
    lines = im.aggregate_iterables(columns)
    lines = ['\t'.join(l) for l in lines]

    output_file = fo.join_paths(output_directory, [ct.RESULTS_ALLELES_BASENAME])
    fo.write_lines(lines, output_file)


def write_results_statistics(classification_files, input_identifiers,
                             output_directory):
    """ Writes a TSV file with classification counts per input.

    Parameters
    ----------
    classification_files : dict
        Dictionary with the paths to loci FASTA files as keys
        and paths to loci classification files as values.
    input_identifiers : dict
        Dictionary with input integer identifiers as keys
        and input string identifiers as values.
    output_directory : str
        Path to the output directory where the TSV file will
        be created.
    """

    # initialize classification counts per input
    class_counts = {i: {c: 0 for c in ct.ALLELECALL_CLASSIFICATIONS}
                    for i in input_identifiers}
    for file in classification_files.values():
        locus_id = fo.get_locus_id(file)
        if locus_id is None:
            locus_id = fo.file_basename(file).split('_results')[0]
        locus_results = fo.pickle_loader(file)

        for i in class_counts:
            if i in locus_results:
                class_counts[i][locus_results[i][0]] += 1
            else:
                class_counts[i]['LNF'] += 1

    # substitute integer identifiers by string identifiers
    class_counts = {input_identifiers[i]: v for i, v in class_counts.items()}

    # initialize with header line
    lines = [['FILE'] + ct.ALLELECALL_CLASSIFICATIONS]
    for k, v in class_counts.items():
        input_line = [k] + [str(v[c]) for c in ct.ALLELECALL_CLASSIFICATIONS]
        lines.append(input_line)

    outlines = ['\t'.join(l) for l in lines]

    output_file = fo.join_paths(output_directory, ['results_statistics.tsv'])
    fo.write_lines(outlines, output_file)


def write_results_contigs(classification_files, input_identifiers,
                          output_directory, cds_coordinates_files):
    """ Writes a TSV file with coding sequence coordinates
        (contig identifier, start and stop positions and coding
        strand) for EXC and INF classifications or with the
        classification type if it is not EXC or INF.

    Parameters
    ----------
    classification_files : list
        List with the paths to loci classification files.
    input_identifiers : dict
        Dictionary with input integer identifiers as keys
        and input string identifiers as values.
    output_directory : str
        Path to the output directory where the TSV file will
        be created.
    cds_coordinates_files : dict
        Dictionary with input string identifiers as keys
        and paths to pickled files with coding sequence
        coordinates as values.

    Returns
    -------
    output_file : str
        Path to the output file that contains the sequence
        coordinates.
    """

    invalid_classes = ct.ALLELECALL_CLASSIFICATIONS[2:]
    intermediate_file = fo.join_paths(output_directory, ['inter_results_contigsInfo.tsv'])
    columns = [['FILE'] + list(input_identifiers.values())]
    # limit the number of lines to store in memory
    line_limit = 500
    for i, file in enumerate(classification_files):
        locus_id = fo.get_locus_id(file)
        if locus_id is None:
            locus_id = fo.file_basename(file).split('_results')[0]
        locus_results = fo.pickle_loader(file)
        column = [locus_id]
        # get sequence hash for exact and inferred
        # get classification for other cases
        column += [locus_results[i][1][2]
                   if i in locus_results and locus_results[i][0] not in invalid_classes
                   else locus_results.get(i, ['LNF'])[0]
                   for i in input_identifiers]

        columns.append(column)

        if len(columns) >= line_limit or (i+1) == len(classification_files):
            inter_lines = [im.join_list(c, '\t') for c in columns]
            fo.write_lines(inter_lines, intermediate_file, write_mode='a')
            columns = []

    # transpose intermediate file
    transposed_file = fo.transpose_matrix(intermediate_file, output_directory)

    # use CDS hash to get coordinates in origin input
    output_file = fo.join_paths(output_directory, ['results_contigsInfo.tsv'])
    with open(transposed_file, 'r') as infile:
        csv_reader = csv.reader(infile, delimiter='\t')
        header = csv_reader.__next__()
        output_lines = [header]
        for i, l in enumerate(csv_reader):
            genome_id = l[0]
            # open file with loci coordinates
            coordinates = fo.pickle_loader(cds_coordinates_files[genome_id])[0]
            # start position is 0-based, stop position is upper-bound exclusive
            cds_coordinates = [coordinates[c][0]
                               if c in coordinates else c
                               for c in l[1:]]

            # contig identifier, start and stop positions and strand
            # 1 for sense, 0 for antisense
            cds_coordiantes_line = ['{0}&{1}-{2}&{3}'.format(*c[:3], c[4])
                                    if c not in invalid_classes else c
                                    for c in cds_coordinates]

            output_lines.append([genome_id]+cds_coordiantes_line)

            if len(output_lines) >= line_limit or (i+1) == len(input_identifiers):
                output_lines = ['\t'.join(l) for l in output_lines]
                fo.write_lines(output_lines, output_file, write_mode='a')
                output_lines = []

    # delete intermediate files
    fo.remove_files([intermediate_file, transposed_file])

    return output_file


def create_unclassified_fasta(fasta_file, prot_file, unclassified_protids,
                              protein_hashtable, output_directory, inv_map):
    """ Creates FASTA file with the distinct coding sequences
        that were not classified.

    Parameters
    ----------
    fasta_file : str
        Path to FASTA file that contains the distinct coding
        sequences identified in the inputs.
    prot_file : str
        Path to FASTA file that contains the distinct translated
        coding sequences identified in the inputs.
    unclassified_protids : list
        List with the sequence identifiers of the representative
        sequences that were not classified.
    protein_hashtable : dict
        Dictionary with SHA-256 hashes for distinct DNA
        sequences extracted from the inputs and lists of
        genome integer identifiers enconded with the
        polyline algorithm as values.
    output_directory : str
        Path to the output directory where the file will be
        created.
    inv_map : dict
        Dictionary with input integer identifiers as keys
        and input string identifiers as values.
    """

    unclassified_seqids = []
    prot_distinct_index = fao.index_fasta(prot_file)
    for protid in unclassified_protids:
        prot_seq = str(prot_distinct_index[protid].seq)
        # determine hash
        prot_hash = im.hash_sequence(prot_seq)
        # get all seqids for DNA sequences that code for protein
        seqids = im.polyline_decoding(protein_hashtable[prot_hash])
        # pairs of protein_id, input_id
        seqids = ['{0}-protein{1}'.format(inv_map[seqids[i]], seqids[i+1])
                  for i in range(0, len(seqids), 2)]
        unclassified_seqids.extend(seqids)

    output_file = fo.join_paths(output_directory, [ct.UNCLASSIFIED_BASENAME])
    dna_index = fao.index_fasta(fasta_file)
    # create FASTA file with unclassified CDSs
    fao.get_sequences_by_id(dna_index, unclassified_seqids, output_file)


def assign_allele_ids(classification_files):
    """ Assigns allele identifiers to coding sequences
        classified as EXC or INF.

    Parameters
    ----------
    classification_files : dict
        Dictionary with the paths to loci FASTA files as keys
        and paths to loci classification files as values.

    Returns
    -------
    novel_alleles : dict
        Dictionary with paths to loci FASTA files as keys and
        lists with SHA-256 hashes and allele integer identifiers
        for each novel allele.
    """

    # assign allele identifiers
    novel_alleles = {}
    for locus, results in classification_files.items():
        # import locus records
        records = fao.import_sequences(locus)
        # determine hash for all locus alleles
        matched_alleles = {im.hash_sequence(v): k.split('_')[-1]
                           for k, v in records.items()}
        # get greatest allele integer identifier
        max_alleleid = max([int(rec.split('_')[-1])
                            for rec in records])
        # import allele calling results and sort to get INF first
        locus_results = fo.pickle_loader(results)
        sorted_results = sorted(locus_results.items(),
                                key=lambda x: x[1][0] == 'INF',
                                reverse=True)

        for k in sorted_results:
            genome_id = k[0]
            current_results = k[1]
            if current_results[0] in ['EXC', 'INF']:
                # get match that was EXC or INF
                current_match = [c for c in current_results[1:]
                                 if c[3] in ['EXC', 'INF']][0]
                cds_hash = current_match[2]
                if cds_hash in matched_alleles:
                    locus_results[genome_id].append(matched_alleles[cds_hash])
                else:
                    # possible to have EXC match to INF that was converted to NIPH
                    max_alleleid += 1
                    locus_results[genome_id].append('INF-{0}'.format(max_alleleid))
                    matched_alleles[cds_hash] = str(max_alleleid)
                    # add the unique SHA256 value
                    novel_alleles.setdefault(locus, []).append([cds_hash, str(max_alleleid)])
                    # EXC to INF to enable accurate count of INF classifications
                    if current_results[0] == 'EXC':
                        locus_results[genome_id][0] = 'INF'

        # save updated results
        fo.pickle_dumper(locus_results, results)

    return novel_alleles


def add_inferred_alleles(inferred_alleles, inferred_representatives, sequences_file):
    """ Adds inferred alleles to a schema.

    Parameters
    ----------
    inferred_alleles : dict
        Dictionary with paths to loci FASTA files as keys and
        lists with SHA-256 hashes, allele integer identifiers and
        sequence identifiers for each novel allele.
    inferred_representatives : dict
        Dictionary with loci identifiers as keys and lists with
        sequence identifiers, SHA-256 hashes and allele integer
        identifiers for each novel representative allele.
    sequences_file : str
        Path to FASTA file that contains the distinct coding
        sequences identified in the inputs.

    Returns
    -------
    total_inferred : int
        Total number of inferred alleles added to the schema.
    total_representatives : int
        Total number of representative alleles added to the
        schema.
    """

    # create index for Fasta file with distinct CDSs
    sequence_index = fao.index_fasta(sequences_file)

    # count number of novel and representative alleles added to schema
    total_inferred = 0
    total_representative = 0
    for locus, alleles in inferred_alleles.items():
        locus_id = fo.get_locus_id(locus)
        if locus_id is None:
            locus_id = fo.file_basename(locus, False)

        # get novel alleles through indexed Fasta file
        novel_alleles = ['>{0}_{1}\n{2}'.format(locus_id, a[1], str(sequence_index.get(a[2]).seq))
                         for a in alleles]
        # append novel alleles to locus FASTA file
        fo.write_lines(novel_alleles, locus, write_mode='a')

        total_inferred += len(novel_alleles)

        # add representatives
        novel_representatives = inferred_representatives.get(locus_id, None)
        if novel_representatives is not None:
            reps_sequences = ['>{0}_{1}\n{2}'.format(locus_id, a[2], str(sequence_index.get(a[0]).seq))
                              for a in novel_representatives]
            # append novel alleles to file in 'short' directory
            locus_short_path = fo.join_paths(os.path.dirname(locus),
                                             ['short', locus_id+'_short.fasta'])
            fo.write_lines(reps_sequences, locus_short_path, write_mode='a')

            total_representative += len(reps_sequences)

    return [total_inferred, total_representative]


def select_highest_scores(blast_outfile):
    """ Selects highest-scoring matches for each distinct target
        in a TSV file with BLAST results.

    Parameters
    ----------
    blast_outfile : str
        Path to the TSV file created by BLAST.

    Returns
    -------
    best_matches : list
        List with the highest-scoring match/line for each
        distinct target.
    """

    blast_results = fo.read_tabular(blast_outfile)
    # sort results based on decreasing raw score
    blast_results = im.sort_iterable(blast_results,
                                     lambda x: int(x[5]), reverse=True)

    # select matches with highest score for each target
    best_matches = []
    for r in blast_results:
        # only get the best raw score for each target
        if r[4] not in best_matches:
            best_matches.append(r)

    return best_matches


def process_blast_results(blast_results, bsr_threshold, query_scores, inputids_mapping):
    """ Processes BLAST results to determine relevant data
        for classification.

    Parameters
    ----------
    blast_results : list
        List with one sublist per BLAST match (must have one
        sublist per target with the highest-scoring match).
    bsr_threshold : float
        BLAST Score Ratio (BSR) value to select matches. Matches
        will be kept if the computed BSR is equal or greater than
        this value.
    query_scores :  dict
        Dictionary with loci representative sequence identifiers
        as values and a tuple with sequence length and the raw
        score for the self-alignment as value.
    inputids_mapping : dict
        Maping between short sequence identifiers and original
        sequence identifiers.

    Returns
    -------
    match_info : dict
        Dictionary with the distinct target sequence identifiers
        as keys and a tuple with the BSR value, target sequence
        length, query sequence length and query sequence identifier
        for the highest-scoring match for each target as values.
    """

    # replace query and target identifiers if they were simplified to avoid BLAST warnings/errors
    # substituting more than it should?
    if inputids_mapping is not None:
        blast_results = [im.replace_list_values(r, inputids_mapping) for r in blast_results]

    # determine BSR values
    match_info = {}
    for r in blast_results:
        query_id = r[0]
        target_id = r[4]
        raw_score = float(r[6])
        bsr = cf.compute_bsr(raw_score, query_scores[query_id][1])
        # only keep matches above BSR threshold
        if bsr >= bsr_threshold:
            # BLAST has 1-based positions
            qstart = (int(r[1])-1)*3 # subtract 1 to exclude start position
            qend = (int(r[2])*3)+3 # add 3 to count stop codon
            target_length = (int(r[5])*3)+3
            query_length = query_scores[query_id][0]

            match_info[target_id] = (bsr, qstart, qend,
                                     target_length, query_length, query_id)

    return match_info


def expand_matches(match_info, pfasta_index, dfasta_index, dhashtable,
                   phashtable, inv_map):
    """ Expands matches against representative sequences to create
        matches for all inputs that contain the representative
        sequence.

    Parameters
    ----------
    match_info : dict
        Dictionary with the distinct target sequence identifiers
        as keys and a tuple with the BSR value, target sequence
        length, query sequence length and query sequence identifier
        for the highest-scoring match for each target as values.
    pfasta_index : Bio.File._IndexedSeqFileDict
        Fasta file index created with BioPython. Index for the
        distinct protein sequences.
    dfasta_index : Bio.File._IndexedSeqFileDict
        Fasta file index created with BioPython. Index for the
        distinct DNA coding sequences.
    dhashtable : dict
        Dictionary with SHA-256 hashes for distinct DNA
        sequences extracted from the inputs and lists of
        genome integer identifiers enconded with the
        polyline algorithm as values.
    phashtable : dict
        Dictionary with SHA-256 hashes for distinct protein
        sequences extracted from the inputs and lists of
        sequence identifiers enconded with the polyline
        algorithm as values.
    inv_map : dict
        Dictionary with input integer identifiers as keys
        and input string identifiers as values.

    Returns
    -------
    input_matches : dict
        Dictionary with input integer identifiers as keys
        and tuples with information about matches identified
        in the inputs as values.
    """

    input_matches = {}
    for target_id in match_info:
        target_protein = str(pfasta_index.get(target_id).seq)
        target_phash = im.hash_sequence(target_protein)
        target_integers = im.polyline_decoding(phashtable[target_phash])
        target_seqids = ['{0}-protein{1}'.format(inv_map[target_integers[i]], target_integers[i+1])
                         for i in range(0, len(target_integers), 2)]
        for seqid in target_seqids:
            target_cds = str(dfasta_index.get(seqid).seq)
            target_dhash = im.hash_sequence(target_cds)
            # get ids for all genomes with same CDS as representative
            target_inputs = im.polyline_decoding(dhashtable[target_dhash])[1:]
            for i in target_inputs:
                input_matches.setdefault(i, []).append((target_id, target_phash,
                                                        target_dhash, *match_info[target_id]))

    return input_matches


def identify_paralogous(results_contigs_file, output_directory):
    """ Identifies groups of paralogous loci in the schema.

    Parameters
    ----------
    results_contigs_file : str
        Path to the 'results_contigsInfo.tsv' file.
    output_directory : str
        Path to the output directory where the file with
        the list of paralogus loci will be created.

    Returns
    -------
    The total number of paralogous loci detected.
    """

    with open(results_contigs_file, 'r') as infile:
        reader = csv.reader(infile, delimiter='\t')
        loci = (reader.__next__())[1:]

        paralogous = {}
        for l in reader:
            locus_results = l[1:]
            counts = Counter(locus_results)
            paralog_counts = {k: v for k, v in counts.items()
                              if v > 1 and k not in ct.ALLELECALL_CLASSIFICATIONS[2:]}
            for p in paralog_counts:
                duplicate = [loci[i] for i, e in enumerate(locus_results) if e == p]
                for locus in duplicate:
                    if locus not in paralogous:
                        paralogous[locus] = 1
                    else:
                        paralogous[locus] += 1

    paralogous_lines = ['LOCUS\tPC']
    paralogous_lines.extend(['{0}\t{1}'.format(k, v) for k, v in paralogous.items()])
    paralogous_file = fo.join_paths(output_directory, [ct.PARALOGS_BASENAME])
    fo.write_lines(paralogous_lines, paralogous_file)

    return len(paralogous)


def classify_inexact_matches(locus, genomes_matches, inv_map, locus_results_file,
                             locus_mode, temp_directory, size_threshold, blast_score_ratio):
    """ Classifies inexact matches found for a locus. Data about
        matches to new alleles is stored to classify inputs with
        the same sequences as exact matches.

    Parameters
    ----------
    locus : str
        Locus identifier.
    genomes_matches : str
        Path to file with data about matches found in the inputs.
    inv_map : dict
        Dictionary with input integer identifeirs as keys and
        input string identifiers as values.
    locus_results_file : str
        Path to file with classification results for the locus.
    locus_mode : list
        List where wthe first element is the locus allele size mode
        and the second element is a list with the length values for
        all alleles.
    temp_directory : str
        Path to the directory where temporary files will be stored.
    size_threshold : float
        Sequence size variation threshold.
    blast_score_ratio : float
        BLAST Score Ratio value.

    Returns
    -------
    locus_info_file : str
        Path to pickle file with the data about the classification
        of inexact matches (contains dictionary with locus identifier
        as key and a list with the path to the pickle file with the
        locus classifications, locus allele size mode, sequence
        identifiers of the distinct sequences that were classified
        and a list with data about representative candidates as value).
    """

    # import classifications
    locus_results = fo.pickle_loader(locus_results_file)

    # import matches
    genomes_matches = fo.pickle_loader(genomes_matches)

    # initialize lists to store hashes of CDSs that have been classified
    seen_dna = {}
    seen_prot = []
    # initialize list to store sequence identifiers that have been classified
    excluded = []
    representative_candidates = []
    for genome, matches in genomes_matches.items():
        current_g = inv_map[genome]

        for m in matches:
            # get sequence identifier for the representative CDS
            target_seqid = m[0]
            # get allele identifier for the schema representative
            rep_alleleid = m[8]
            # determine if representative has allele id
            try:
                int(rep_alleleid.split('_')[-1])
                rep_alleleid = rep_alleleid.split('_')[-1]
            except Exception as e:
                pass

            # get hash of the CDS DNA sequence
            target_dna_hash = m[2]
            # get hash of the translated CDS sequence
            target_prot_hash = m[1]

            # get the BSR value
            bsr = m[3]

            # CDS DNA sequence was identified in one of the previous inputs
            # This will change classification to NIPH if the input
            # already had a classification for the current locus
            if target_dna_hash in seen_dna:
                locus_results = update_classification(genome, locus_results,
                                                      (seen_dna[target_dna_hash], target_seqid,
                                                       target_dna_hash, 'EXC', 1.0))
                continue

            # translated CDS matches other translated CDS that was classified
            if target_prot_hash in seen_prot:
                locus_results = update_classification(genome, locus_results,
                                                      (rep_alleleid, target_seqid,
                                                       target_dna_hash, 'INF', 1.0))
                # add DNA hash to classify the next match as EXC
                seen_dna[target_dna_hash] = target_seqid
                continue

            # there is no DNA or Protein exact match, perform full evaluation
            # open pickle for genome and get coordinates
            genome_cds_file = fo.join_paths(temp_directory, ['2_cds_extraction', current_g+'_cds_hash'])
            genome_cds_coordinates = fo.pickle_loader(genome_cds_file)
            # classifications based on position on contig (PLOT3, PLOT5 and LOTSC)
            # get CDS start and stop positions
            genome_coordinates = genome_cds_coordinates[0][target_dna_hash][0]
            contig_leftmost_pos = int(genome_coordinates[1])
            contig_rightmost_pos = int(genome_coordinates[2])
            # get contig length
            contig_length = genome_cds_coordinates[1][genome_coordinates[0]]
            # get representative length
            representative_length = m[7]
            # get target left and right positions that aligned
            representative_leftmost_pos = m[4]
            representative_rightmost_pos = m[5]
            # determine if it is PLOT3, PLOT5 or LOTSC
            relative_pos = contig_position_classification(representative_length,
                                                          representative_leftmost_pos,
                                                          representative_rightmost_pos,
                                                          contig_length,
                                                          contig_leftmost_pos,
                                                          contig_rightmost_pos)

            if relative_pos is not None:
                #print(genome, m, genome_coordinates, contig_leftmost_pos, contig_rightmost_pos, contig_length)
                locus_results = update_classification(genome, locus_results,
                                                      (rep_alleleid, target_seqid,
                                                       target_dna_hash, relative_pos, bsr))
                # need to exclude so that it does not duplicate ASM/ALM classifications later
                excluded.append(target_seqid)
                continue

            target_dna_len = m[6]
            # check if ASM or ALM
            relative_size = allele_size_classification(target_dna_len, locus_mode, size_threshold)
            # we only need to evaluate one of the genomes, if they are ASM/ALM we can classify all of them as the same!
            if relative_size is not None:
                locus_results = update_classification(genome, locus_results,
                                                      (rep_alleleid, target_seqid,
                                                       target_dna_hash, relative_size, bsr))
                # need to exclude so that it does not duplicate PLOT3/5 classifications later
                excluded.append(target_seqid)
                continue

            # add INF
            # this will turn into NIPH if there are multiple hits for the same input
            locus_results = update_classification(genome, locus_results,
                                                  (rep_alleleid, target_seqid,
                                                   target_dna_hash, 'INF', bsr))

            seen_dna[target_dna_hash] = target_seqid
            excluded.append(target_seqid)
            seen_prot.append(target_prot_hash)

        # update locus mode value if classification for genome is INF
        if genome in locus_results and locus_results[genome][0] == 'INF':
            # append length of inferred allele to list with allele sizes
            locus_mode[1].append(target_dna_len)
            # compute mode
            locus_mode[0] = sm.determine_mode(locus_mode[1])[0]
            # only add as representative candidate if classification is not NIPH
            inf_bsr = locus_results[genome][1][4]
            if inf_bsr >= blast_score_ratio and inf_bsr < blast_score_ratio+0.1:
                representative_candidates.append((genome, target_seqid,
                                                  m[8], target_dna_hash))

    # save updated results
    fo.pickle_dumper(locus_results, locus_results_file)

    # save info about updated mode, excluded ids and representative candidates
    locus_info = {locus: [locus_results_file, locus_mode,
                          excluded, representative_candidates]}
    locus_info_file = fo.join_paths(temp_directory, ['{0}_classification_info'.format(locus)])
    fo.pickle_dumper(locus_info, locus_info_file)

    return locus_info_file


def create_missing_fasta(class_files, fasta_file, input_map, dna_hashtable,
                         output_directory, coordinates_files):
    """ Creates Fasta file with sequences for missing data classes.

    Parameters
    ----------
    class_files : dict
        Dictionary with paths to loci files as keys and paths to
        pickled files with classification results as values.
    fasta_file : str
        Path to Fasta file with the distinct CDS extracted from
        the input genomes.
    input_map : dict
        Dictionary with the mapping between the input integer
        identifiers and input string identifiers.
    dna_hashtable : dict
        Dictionary with hashes of the distinct CDS extracted from
        input genomes as keys and lists containing the integer
        identifiers for te inputs that contained the CDS encoded
        with the polyline algorithm.
    output_directory : str
        Path to the output directory where the Fasta file will
        be saved to.
    coordinates_files : dict
        Dictionary with the mapping between input string identifiers
        and paths to pickled files that contain a dictionary with the
        coordinates of the CDS identified in each input.
    """

    invalid_cases = ct.ALLELECALL_CLASSIFICATIONS[2:-1]

    # get information about missing cases for each input genome
    missing_cases = {}
    for locus, file in class_files.items():
        locus_id = fo.get_locus_id(locus)
        locus_classifications = fo.pickle_loader(file)
        # get data for genomes that do not have EXC or INF classifications
        # it will not get invalid classes if a genome is classified as EXC or INF
        for gid, v in locus_classifications.items():
            if v[0] in invalid_cases:
                genome_info = [locus_id, v[0], [[e[2], e[3]] for e in v[1:]]]
                missing_cases.setdefault(input_map[gid], []).append(genome_info)

    # get seqids that match hashes
    for k, v in missing_cases.items():
        genome_coordinates = fo.pickle_loader(coordinates_files[k])[0]
        # genomes may have duplicated CDSs
        # store hash and increment i to get correct positions
        hashes = {}
        for c in v:
            locus_id = c[0]
            classification = c[1]
            for h in c[2]:
                current_hash = h[0]
                coordinates = genome_coordinates[current_hash]

                if current_hash not in hashes:
                    hashes[current_hash] = {locus_id: 0}
                else:
                    # multiple matches to the same locus
                    if locus_id in hashes[current_hash]:
                        hashes[current_hash][locus_id] += 1
                    # multiple matches to multiple loci
                    else:
                        hashes[current_hash][locus_id] = 0

                current_index = hashes[current_hash][locus_id]
                protid = coordinates[current_index][3]
                h.append('{0}-protein{1}&{2}|{3}&{4}'.format(k, protid, h[1], c[0], c[1]))

    missing_records = []
    dna_index = fao.index_fasta(fasta_file)
    for genome, v in missing_cases.items():
        current_records = []
        for c in v:
            for h in c[2]:
                hash_entry = im.polyline_decoding(dna_hashtable[h[0]])
                seqid = '{0}-protein{1}'.format(input_map[hash_entry[1]], hash_entry[0])
                new_rec = fao.fasta_str_record(h[2], str(dna_index[seqid].seq))
                current_records.append(new_rec)

        missing_records.extend(current_records)

    output_file = fo.join_paths(output_directory, ['missing_classes.fasta'])
    fo.write_lines(missing_records, output_file)


def select_representatives(representative_candidates, locus, fasta_file, iteration, output_directory,
                           blastp_path, blast_db, blast_score_ratio,
                           threads):
    """ Selects new representative alleles for a locus from a set of
        candidate alleles.

    Parameters
    ----------
    representative_candidates : dict
        Dictionary with sequence identifiers as keys and sequence
        hashes as values.
    locus : str
        Locus identifier.
    fasta_file : path
        Path to Fasta file that contains the translated sequences
        of the representative candidates.
    iteration : int
        Iteration number to add to generated files.
    output_directory : str
        Path to the output directory.
    blastp_path : str
        Path to the BLASTp executable.
    blast_db : str
        Path to the BLAST database.
    blast_score_ratio : float
        BLAST Score Ratio value.
    threads : int
        Number of threads passed to BLAST.

    Returns
    -------
    locus : str
        Locus identifier.
    selected : list
        List that contains one tuple per selected candidate (tuples
        contain the sequence identifier and the sequence hash for
        each new representative).
    """

    # create file with candidate ids
    ids_file = fo.join_paths(output_directory,
                             ['{0}_candidates_ids_{1}.fasta'.format(locus, iteration)])
    fo.write_lines(list(representative_candidates.keys()), ids_file)

    # BLASTp to compare all candidates
    blast_output = fo.join_paths(output_directory,
                                 ['{0}_candidates_{1}_blastout.tsv'.format(locus, iteration)])
    # pass number of max targets per query to reduce execution time
    blastp_stderr = bw.run_blast(blastp_path, blast_db, fasta_file,
                                 blast_output, threads=threads,
                                 ids_file=ids_file, max_targets=30)

    blast_results = fo.read_tabular(blast_output)
    # get self scores
    candidates_self_scores = {l[0]: ((int(l[3])*3)+3, float(l[6]))
                              for l in blast_results if l[0] == l[4]}
    # select results between different candidates
    blast_results = [l for l in blast_results if l[0] != l[4]]

    # compute bsr
    for l in blast_results:
        l.append(cf.compute_bsr(candidates_self_scores[l[4]][1], candidates_self_scores[l[0]][1]))
    # sort by sequence length to process longest candidates first
    blast_results = sorted(blast_results, key= lambda x: int(x[3]))

    excluded_candidates = []
    for r in blast_results:
        if r[7] >= blast_score_ratio+0.1:
            if r[4] not in excluded_candidates:
                excluded_candidates.append(r[0])

    selected_candidates = list(set([l[0]
                                    for l in blast_results
                                    if l[0] not in excluded_candidates]))

    selected = [(l, representative_candidates[l])
                for l in selected_candidates
                if l not in excluded_candidates]

    return [locus, selected]


# input_file = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/ids32.txt'
# input_file = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/ids_plot.txt'
# input_file = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/test_chewie3/ids.txt'
# fasta_files = fo.read_lines(input_file, strip=True)
# fasta_files = im.sort_iterable(fasta_files, sort_key=str.lower)
# output_directory = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/test_chewie3/test_allelecall'
# ptf_path = '/home/rfm/Lab_Software/AlleleCall_tests/test_chewie3/senterica_schema/Salmonella_enterica.trn'
# blast_score_ratio = 0.6
# minimum_length = 201
# translation_table = 11
# size_threshold = 0.2
# word_size = 5
# window_size = 5
# clustering_sim = 0.2
# representative_filter = 0.9
# intra_filter = 0.9
# cpu_cores = 6
# blast_path = '/home/rfm/Software/anaconda3/envs/spyder/bin'
# prodigal_mode = 'single'
# cds_input = False
# only_exact = False
# schema_directory = '/home/rfm/Lab_Software/AlleleCall_tests/test_chewie3/senterica_schema'
# #schema_directory = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/test_schema'
# add_inferred = True
# output_unclassified = False
# output_missing = False
# no_cleanup = True
def allele_calling(fasta_files, schema_directory, output_directory, ptf_path,
                   blast_score_ratio, minimum_length, translation_table,
                   size_threshold, word_size, window_size, clustering_sim,
                   cpu_cores, blast_path, prodigal_mode, cds_input,
                   only_exact):
    """
    """

    # define directory for temporary files
    temp_directory = fo.join_paths(output_directory, ['temp'])
    fo.create_directory(temp_directory)

    # map full paths to basename
    inputs_basenames = im.mapping_function(fasta_files,
                                           fo.file_basename, [False])

    # map input identifiers to integers
    # use the mapped integers to refer to each input
    # this reduces memory usage compared to using string identifiers
    basename_map = im.integer_mapping(inputs_basenames.values())
    basename_inverse_map = im.invert_dictionary(basename_map)

    # inputs are genome assemblies
    if cds_input is False:
        print('Number of inputs: {0}'.format(len(fasta_files)))

        # create directory to store files with Prodigal results
        prodigal_path = fo.join_paths(temp_directory, ['1_gene_prediction'])
        fo.create_directory(prodigal_path)

        # run Prodigal to determine CDSs for all input genomes
        print('\nPredicting gene sequences...\n')

        # gene prediction step
        gp_results = cf.predict_genes(fasta_files, ptf_path,
                                      translation_table, prodigal_mode,
                                      cpu_cores, prodigal_path,
                                      output_directory)

        if gp_results is not None:
            failed, failed_file = gp_results

            print('\nFailed to predict genes for {0} genomes'
                  '.'.format(len(failed)))
            print('Make sure that Prodigal runs in meta mode (--pm meta) '
                  'if any input file has less than 100kbp.')
            print('Info for failed cases stored in: {0}'.format(failed_file))

            # remove failed genomes from paths
            fasta_files = im.filter_list(fasta_files, failed)

        if len(fasta_files) == 0:
            sys.exit('\nCould not predict gene sequences from any '
                     'of the input files.\nPlease provide input files '
                     'in the accepted FASTA format.')

        # CDS extraction step
        print('\n\nExtracting coding sequences...\n')
        # create output directory
        cds_extraction_path = fo.join_paths(temp_directory,
                                            ['2_cds_extraction'])
        fo.create_directory(cds_extraction_path)
        eg_results = cf.extract_genes(fasta_files, prodigal_path,
                                      cpu_cores, cds_extraction_path,
                                      output_directory)
        cds_files, total_extracted = eg_results

        print('\n\nExtracted a total of {0} coding sequences from {1} '
              'genomes.'.format(total_extracted, len(fasta_files)))
    # inputs are Fasta files with the predicted CDSs
    else:
        cds_files = fasta_files
        print('Number of inputs: {0}'.format(len(cds_files)))

    # create directory to store files from pre-process steps
    preprocess_dir = fo.join_paths(temp_directory, ['3_cds_preprocess'])
    fo.create_directory(preprocess_dir)

    # DNA sequences deduplication step
    # keep hash of unique sequences and a list with the integer
    # identifiers of genomes that have those sequences
    # lists of integers are encoded with polyline algorithm
    print('\nRemoving duplicated DNA sequences...', end='')
    distinct_dna_template = 'distinct_cds_{0}.fasta'
    dna_dedup_results = cf.exclude_duplicates(cds_files, preprocess_dir,
                                              cpu_cores, distinct_dna_template,
                                              basename_map, False, True)

    dna_distinct_htable, distinct_file, repeated = dna_dedup_results
    print('removed {0} sequences.'.format(repeated))

    print('Kept {0} distinct sequences.'.format(len(dna_distinct_htable)))

    # get list of loci files
    print('Getting list of loci...', end='')
    loci_files = fo.listdir_fullpath(schema_directory, '.fasta')
    
    # get mapping between locus file path and locus identifier
    loci_basenames = im.mapping_function(loci_files, fo.file_basename, [False])
    print('schema has {0} loci.'.format(len(loci_files)))

    # create files with empty results data structure
    classification_dir = fo.join_paths(temp_directory, ['4_classification_files'])
    fo.create_directory(classification_dir)
    empty_results = {}
    inputs = [[loci_basenames[file], classification_dir, empty_results]
              for file in loci_files]
    classification_files = {file: create_classification_file(*inputs[i])
                            for i, file in enumerate(loci_files)}

    # get size mode for all loci
    loci_modes_file = fo.join_paths(schema_directory, ['loci_modes'])
    if os.path.isfile(loci_modes_file) is True:
        loci_modes = fo.pickle_loader(loci_modes_file)
    else:
        print('\nDetermining sequence length mode for all loci...', end='')
        loci_modes = {}
        for file in loci_files:
            alleles_sizes = list(fao.sequences_lengths(file).values())
            # select first value in list if there are several values with same frequency
            loci_modes[loci_basenames[file]] = [sm.determine_mode(alleles_sizes)[0], alleles_sizes]
        fo.pickle_dumper(loci_modes, loci_modes_file)

    print('Finding DNA exact matches...', end='')
    matched_seqids = []
    dna_exact_hits = 0
    dna_matches_ids = 0
    for locus, results_file in classification_files.items():
        locus_classifications = fo.pickle_loader(results_file)
        em_results = dna_exact_matches(locus, dna_distinct_htable,
                                       locus_classifications, basename_inverse_map)
        # save updated classifications
        fo.pickle_dumper(em_results[0], results_file)
        # extend list of matched seqids
        matched_seqids.extend(em_results[1])
        dna_exact_hits += em_results[2]
        dna_matches_ids += len(em_results[1])

    print('found {0} exact matches (matching {1} distinct alleles).'
          ''.format(dna_exact_hits, dna_matches_ids))

    # user only wants to determine exact matches
    if only_exact is True:
        # return classification files to create output files
        return [classification_files, basename_inverse_map, []]

    # create Fasta file without distinct sequences that were exact matches
    dna_index = fao.index_fasta(distinct_file)

    # get sequence identifiers for unclassified sequences
    # reading to get lines with '>' is faster that reading with BioPython
    # and filtering based on sequence identifiers
    matched_lines = fo.matching_lines(distinct_file, '>')
    matched_lines = [l.strip()[1:] for l in matched_lines]
    selected_ids = im.filter_list(matched_lines, matched_seqids)

    print('Remaining: {0}'.format(len(selected_ids)))

    # translate DNA sequences and identify duplicates
    print('\nTranslating {0} DNA sequences...'.format(len(selected_ids)))

    # this step excludes small sequences
    ts_results = cf.translate_sequences(selected_ids, distinct_file,
                                        preprocess_dir, translation_table,
                                        minimum_length, cpu_cores)

    dna_file, protein_file, ut_seqids, ut_lines = ts_results

    print('Removed {0} DNA sequences that could not be '
          'translated.'.format(len(ut_seqids)))

    print('Remaining: {0}'.format(len(selected_ids)-len(ut_seqids)))

    # write info about invalid alleles to file
    invalid_alleles_file = fo.join_paths(output_directory,
                                         ['invalid_cds.txt'])
    invalid_alleles = im.join_list(ut_lines, '\n')
    fo.write_to_file(invalid_alleles, invalid_alleles_file, 'w', '\n')
    print('Info about untranslatable and small sequences '
          'stored in {0}'.format(invalid_alleles_file))

    # protein sequences deduplication step
    print('\nRemoving duplicated protein sequences...', end='')
    distinct_prot_template = 'distinct_prots_{0}.fasta'
    ds_results = cf.exclude_duplicates([protein_file], preprocess_dir, 1,
                                       distinct_prot_template, basename_map, True)
    print('removed {0} sequences.'.format(ds_results[2]))
    distinct_pseqids = ds_results[0]

    print('Distinct proteins: {0}'.format(len(distinct_pseqids)))

    # translate loci files
    print('Translating schema alleles...')
    protein_dir = fo.join_paths(temp_directory, ['4_protein_dir'])
    fo.create_directory(protein_dir)
    protein_files = mo.parallelize_function(fao.translate_fasta, loci_files,
                                            [protein_dir, translation_table],
                                            cpu_cores, True)
    protein_files = {r[0]: r[1] for r in protein_files}

    # identify exact matches at protein level
    # exact matches are novel alleles that can be added to the schema
    print('\nFinding protein exact matches...', end='')
    exc_cds = 0
    exc_prot = 0
    exc_distinct_prot = 0
    exact_phashes = []
    for locus, pfile in protein_files.items():
        results_file = classification_files[locus]
        locus_classifications = fo.pickle_loader(results_file)
        em_results = protein_exact_matches(pfile, distinct_pseqids,
                                           dna_distinct_htable, locus_classifications,
                                           dna_index, basename_inverse_map)

        fo.pickle_dumper(em_results[0], results_file)
        exact_phashes.extend(em_results[1])
        exc_prot += em_results[2]
        exc_cds += em_results[3]
        exc_distinct_prot += em_results[-1]

    print('found {0} protein exact matches ({1} distinct CDSs, {2} total CDSs).'
          ''.format(exc_distinct_prot, exc_prot, exc_cds))

    # create new Fasta file without the Protein sequences that were exact matches
    unique_pfasta = fo.join_paths(preprocess_dir, ['protein_non_exact.fasta'])
    # create protein file index
    protein_index = fao.index_fasta(ds_results[1])
    # the list of "exact_phases" corresponds to the seqids for the DNA sequences
    # this means that it can have more elements that the number of protein exact matches
    # because different alleles might code for same protein
    matched_lines = fo.matching_lines(ds_results[1], '>')
    matched_lines = [l.strip()[1:] for l in matched_lines]
    selected_ids = im.filter_list(matched_lines, exact_phashes)
    total_selected = fao.get_sequences_by_id(protein_index, selected_ids, unique_pfasta)

    print('Remaining: {0}'.format(total_selected))

    # translate schema representatives
    print('Translating schema representatives...')
    rep_dir = fo.join_paths(schema_directory, ['short'])
    rep_list = fo.listdir_fullpath(rep_dir, '.fasta')

    protein_files = mo.parallelize_function(fao.translate_fasta, rep_list,
                                            [protein_dir, translation_table],
                                            cpu_cores, True)
    protein_repfiles = [r[1] for r in protein_files]

    # cluster protein sequences
    proteins = fao.import_sequences(unique_pfasta)

    # create directory to store clustering data
    clustering_dir = fo.join_paths(temp_directory, ['5_clustering'])
    fo.create_directory(clustering_dir)

    # define BLASTp and makeblastdb paths
    blastp_path = fo.join_paths(blast_path, [ct.BLASTP_ALIAS])
    makeblastdb_path = fo.join_paths(blast_path, [ct.MAKEBLASTDB_ALIAS])

    # concatenate all schema representative
    concat_reps = fo.join_paths(protein_dir, ['concat_reps.fasta'])
    fo.concatenate_files(protein_repfiles, concat_reps)

    # determine self-score for representatives if file is missing
    self_score_file = fo.join_paths(schema_directory, ['short', 'self_scores'])
    if os.path.isfile(self_score_file) is False:
        self_scores = fao.determine_self_scores(temp_directory, concat_reps,
                                                makeblastdb_path, blastp_path,
                                                'prot', cpu_cores)
        fo.pickle_dumper(self_scores, self_score_file)
    else:
        self_scores = fo.pickle_loader(self_score_file)

    # create Kmer index for representatives
    representatives = im.kmer_index(concat_reps, 5)

    # cluster CDSs into representative clusters
    # this is not reporting the correct number of sequences added to clusters!
    cs_results = cf.cluster_sequences(proteins, word_size, window_size,
                                      clustering_sim, representatives, False,
                                      1, 30, clustering_dir, cpu_cores,
                                      'clusters', True, False)

    # exclude singletons
    clusters = {k: v for k, v in cs_results.items() if len(v) > 0}

    # BLASTp if there are clusters with n>1
    if len(clusters) > 0:
        blasting_dir = fo.join_paths(clustering_dir, ['cluster_blaster'])
        fo.create_directory(blasting_dir)
        all_prots = fo.join_paths(blasting_dir, ['all_prots.fasta'])

        # create Fasta file with remaining proteins and representatives
        fo.concatenate_files([unique_pfasta, concat_reps], all_prots)

        all_proteins = fao.import_sequences(all_prots)

        # BLAST clustered sequences against cluster representatives
        blast_results, ids_dict = cf.blast_clusters(clusters, all_proteins,
                                                    blasting_dir, blastp_path,
                                                    makeblastdb_path, cpu_cores,
                                                    'blast', True)

        blast_files = im.flatten_list(blast_results)

    # concatenate results for representatives of the same locus
    loci_results = {}
    for f in blast_files:
        locus_rep = ids_dict[im.match_regex(f, r'seq_[0-9]+')]
        locus_id = im.match_regex(locus_rep, r'^.+-protein[0-9]+')
        # for schemas that do not have 'protein' in the identifier
        # would fail for schemas from Chewie-NS
        if locus_id is None:
            locus_id = '_'.join(locus_rep.split('_')[0:-1])
        loci_results.setdefault(locus_id, []).append(f)

    concatenated_files = []
    concatenate_file_template = '{0}.concatenated_blastout.tsv'
    for locus, files in loci_results.items():
        outfile = fo.join_paths(clustering_dir,
                                [concatenate_file_template.format(locus)])
        fo.concatenate_files(files, outfile)
        concatenated_files.append(outfile)

    # create index for distinct protein sequences
    prot_index = fao.index_fasta(all_prots)

    loci_results = {}
    for f in concatenated_files:
        locus_id = fo.get_locus_id(f)
        if locus_id is None:
            locus_id = fo.file_basename(f).split('.concatenated')[0]
        # exclude results in the BSR+0.1 threshold
        # process representative candidates in later stage
        best_matches = select_highest_scores(f)
        match_info = process_blast_results(best_matches, blast_score_ratio+0.1,
                                           self_scores, ids_dict)
        locus_results = expand_matches(match_info, prot_index, dna_index,
                                       dna_distinct_htable, distinct_pseqids, basename_inverse_map)

        if len(locus_results) > 0:
            # save results to file
            locus_file = fo.join_paths(blasting_dir, ['{0}_locus_matches'.format(locus_id)])
            fo.pickle_dumper(locus_results, locus_file)
            loci_results[locus_id] = locus_file

    # process results per genome and per locus
    print('Classification...')
    classification_inputs = []
    for locus, file in loci_results.items():
        # get locus length mode
        locus_mode = loci_modes[locus]

        # import file with locus classifications
        locus_results_file = fo.join_paths(classification_dir, [locus+'_results'])

        classification_inputs.append([locus, file,
                                      basename_inverse_map,
                                      locus_results_file, locus_mode,
                                      temp_directory, size_threshold,
                                      blast_score_ratio,
                                      classify_inexact_matches])

    class_results = mo.map_async_parallelizer(classification_inputs,
                                              mo.function_helper,
                                              cpu_cores,
                                              show_progress=True)

    excluded = []
    for r in class_results:
        current_results = fo.pickle_loader(r)
        for locus, v in current_results.items():
            # this does not include the length of alleles inferred through protein exact matches
            loci_modes[locus] = v[1]
            excluded.extend(v[2])

    # may have repeated elements due to same CDS matching different loci
    excluded = set(excluded)
    print('\nExcluded distinct proteins: {0}'.format(len(excluded)))

    # get seqids of remaining unclassified sequences
    unclassified_ids = [rec.id
                        for rec in SeqIO.parse(unique_pfasta, 'fasta')
                        if rec.id not in excluded]
    print('Remaining: {0}'.format(len(unclassified_ids)))

    # create directory to store data for each iteration
    iterative_rep_dir = fo.join_paths(temp_directory, ['6_iterative_reps'])
    fo.create_directory(iterative_rep_dir)

    remaining_seqs_file = fo.join_paths(iterative_rep_dir, ['remaining_prots.fasta'])
    # create Fasta with unclassified sequences
    fao.get_sequences_by_id(prot_index, unclassified_ids,
                            remaining_seqs_file, limit=50000)

    # shorten ids to avoid BLASTp error?
    blast_db = fo.join_paths(iterative_rep_dir, ['blastdb'])
    # will not work if file contains duplicated seqids
    db_stderr = bw.make_blast_db(makeblastdb_path, remaining_seqs_file,
                                 blast_db, 'prot')

    # get seqids of schema representatives
    reps_ids = [rec.id for rec in SeqIO.parse(concat_reps, 'fasta')]
    print('Schema has a total of {0} representative alleles.'
          ''.format(len(reps_ids)))

    # BLAST schema representatives against remaining unclassified CDSs
    new_reps = {}
    iteration = 1
    exausted = False
    # keep iterating while new representatives are discovered
    while exausted is False:
        # create text file with unclassified seqids
        remaining_seqsids_file = fo.join_paths(iterative_rep_dir, ['remaining_seqids_{0}.txt'.format(iteration)])
        fo.write_lines(unclassified_ids, remaining_seqsids_file)
        # BLAST representatives against remaining sequences
        # iterative process until the process does not detect new representatives
        print('Representative sets to BLAST against remaining '
              'sequences: {0} ({1} representatives)\n'
              ''.format(len(protein_repfiles), len(self_scores)))

        # create BLASTp inputs
        output_files = []
        blast_inputs = []
        for file in protein_repfiles:
            locus_id = fo.get_locus_id(file)
            if locus_id is None:
                # need to add 'short' or locus id will not be split
                locus_id = fo.file_basename(file).split('_short')[0]
            outfile = fo.join_paths(iterative_rep_dir,
                                    [locus_id+'_blast_results_iter{0}.tsv'.format(iteration)])
            output_files.append(outfile)

            blast_inputs.append([blastp_path, blast_db, file, outfile,
                                 1, 1, remaining_seqsids_file, bw.run_blast])

        # BLAST representatives against unclassified sequences
        print('BLASTing...\n')
        blastp_results = mo.map_async_parallelizer(blast_inputs,
                                                   mo.function_helper,
                                                   cpu_cores,
                                                   show_progress=True)

        loci_results = {}
        for f in output_files:
            locus_id = fo.get_locus_id(f)
            if locus_id is None:
                locus_id = fo.file_basename(f).split('_blast')[0]
            best_matches = select_highest_scores(f)
            match_info = process_blast_results(best_matches, blast_score_ratio,
                                               self_scores, None)
            locus_results = expand_matches(match_info, prot_index, dna_index,
                                           dna_distinct_htable, distinct_pseqids, basename_inverse_map)

            if len(locus_results) > 0:
                locus_file = fo.join_paths(iterative_rep_dir, ['{0}_locus_matches'.format(locus_id)])
                fo.pickle_dumper(locus_results, locus_file)
                loci_results[locus_id] = locus_file

        print('\nLoci with new hits: '
              '{0}'.format(len(loci_results)))

        if len(loci_results) == 0:
            exausted = True
            continue

        # process results per genome and per locus
        print('Classification...')
        classification_inputs = []
        for locus, file in loci_results.items():
            # get locus length mode
            locus_mode = loci_modes[locus]

            # import file with locus classifications
            locus_results_file = fo.join_paths(classification_dir, [locus+'_results'])

            classification_inputs.append([locus, file,
                                          basename_inverse_map,
                                          locus_results_file, locus_mode,
                                          temp_directory, size_threshold,
                                          blast_score_ratio,
                                          classify_inexact_matches])

        class_results = mo.map_async_parallelizer(classification_inputs,
                                                  mo.function_helper,
                                                  cpu_cores,
                                                  show_progress=True)

        # may have repeated elements due to same CDS matching different loci
        excluded = []
        representative_candidates = {}
        for r in class_results:
            current_results = fo.pickle_loader(r)
            for locus, v in current_results.items():
                loci_modes[locus] = v[1]
                excluded.extend(v[2])
                if len(v[3]) > 0:
                    representative_candidates[locus] = v[3]

        # remove representative candidates ids from excluded
        excluded = set(excluded)

        # include new representatives
        print('Classified {0} proteins.'.format(len(excluded)))

        # exclude sequences that were excluded
        unclassified_ids = set(unclassified_ids) - excluded

        # new representatives and alleles that amtch in other genomes should have been all classified
        print('Remaining unclassified proteins: {0}'.format(len(unclassified_ids)))

        representatives = {}
        representative_inputs = []
        if len(representative_candidates) > 0:
            print('\nSelecting representatives for next iteration.')
            for k, v in representative_candidates.items():
                if len(v) > 1:
                    current_candidates = {e[1]: e[3] for e in v}
                    fasta_file = fo.join_paths(iterative_rep_dir,
                                   ['{0}_candidates_{1}.fasta'.format(k, iteration)])
                    # create file with sequences
                    fao.get_sequences_by_id(prot_index, list(current_candidates.keys()), fasta_file)
                    representative_inputs.append([current_candidates, k, fasta_file,
                                                  iteration, iterative_rep_dir, blastp_path,
                                                  blast_db, blast_score_ratio, 1,
                                                  select_representatives])
                else:
                    representatives[k] = [(v[0][1], v[0][3])]
    
            selected_candidates = mo.map_async_parallelizer(representative_inputs,
                                                            mo.function_helper,
                                                            cpu_cores,
                                                            show_progress=True)
    
            for c in selected_candidates:
                representatives[c[0]] = c[1]
    
            for k, v in representatives.items():
                new_reps.setdefault(k, []).extend(v)

        # stop iterating if there are no new representatives
        if len(representatives) == 0:
            exausted = True
        else:
            iteration += 1
            # create files with representative sequences
            reps_ids = []
            protein_repfiles = []
            for k, v in representatives.items():
                # get new representative for locus
                current_new_reps = [e[0] for e in v]
                reps_ids.extend(current_new_reps)
                
                # need to add 'short' or locus id will not be split
                rep_file = fo.join_paths(iterative_rep_dir,
                                         ['{0}_short_reps_iter{1}.fasta'.format(k, iteration)])
                fao.get_sequences_by_id(prot_index, current_new_reps, rep_file)
                protein_repfiles.append(rep_file)

            # concatenate reps
            concat_repy = fo.join_paths(iterative_rep_dir, ['{0}_concat_reps.fasta'.format(iteration)])
            fao.get_sequences_by_id(prot_index, set(reps_ids), concat_repy, limit=50000)
            # determine self-score for new reps
            new_self_scores = fao.determine_self_scores(iterative_rep_dir, concat_repy,
                                                        makeblastdb_path, blastp_path,
                                                        'prot', cpu_cores)

            self_scores = {**self_scores, **new_self_scores}

    return [classification_files, basename_inverse_map, distinct_file, all_prots,
            dna_distinct_htable, distinct_pseqids, new_reps, self_scores,
            unclassified_ids]


def main(input_file, schema_directory, output_directory, ptf_path,
         blast_score_ratio, minimum_length, translation_table,
         size_threshold, word_size, window_size, clustering_sim,
         cpu_cores, blast_path, cds_input, prodigal_mode, only_exact,
         add_inferred, output_unclassified, output_missing,
         no_cleanup):

    print('Prodigal training file: {0}'.format(ptf_path))
    print('CPU cores: {0}'.format(cpu_cores))
    print('BLAST Score Ratio: {0}'.format(blast_score_ratio))
    print('Translation table: {0}'.format(translation_table))
    print('Minimum sequence length: {0}'.format(minimum_length))
    print('Size threshold: {0}'.format(size_threshold))
    print('Word size: {0}'.format(word_size))
    print('Window size: {0}'.format(window_size))
    print('Clustering similarity: {0}'.format(clustering_sim))

    start_time = pdt.get_datetime()

    # read file with paths to input files
    input_files = fo.read_lines(input_file, strip=True)

    # sort paths to FASTA files
    input_files = im.sort_iterable(input_files, sort_key=str.lower)

    results = allele_calling(input_files, schema_directory, output_directory,
                             ptf_path, blast_score_ratio, minimum_length,
                             translation_table, size_threshold, word_size,
                             window_size, clustering_sim, cpu_cores, blast_path,
                             prodigal_mode, cds_input, only_exact)

    # sort classification files to have allele call matrix format similar to v2.0
    results[0] = {k: results[0][k] for k in sorted(list(results[0].keys()))}

    # assign allele identifiers to novel alleles
    novel_alleles = assign_allele_ids(results[0])

    # count total for each classification type
    global_counts, total_cds = count_classifications(results[0].values())

    print('Classified a total of {0} CDSs.'.format(total_cds))
    print('\n'.join(['{0}: {1}'.format(k, v)
                     for k, v in global_counts.items()]))

    if only_exact is False and add_inferred is True:
        # get seqids that match hashes
        for k, v in novel_alleles.items():
            for r in v:
                rep_seqid = im.polyline_decoding(results[4][r[0]])[0:2]
                rep_seqid = '{0}-protein{1}'.format(results[1][rep_seqid[1]], rep_seqid[0])
                r.append(rep_seqid)

        # get info for new representative alleles that must be added to files in the short directory
        reps_info = {}
        for k, v in novel_alleles.items():
            locus_id = fo.get_locus_id(k)
            if locus_id is None:
                locus_id = fo.file_basename(k, False)
            current_results = results[6].get(locus_id, None)
            if current_results is not None:
                for e in current_results:
                    allele_id = [l[1] for l in v if l[0] == e[1]]
                    # we might have representatives that were converted to NIPH but still appear in the list
                    if len(allele_id) > 0:
                        reps_info.setdefault(locus_id, []).append(list(e)+allele_id)

        # update self_scores
        reps_to_del = set()
        for k, v in reps_info.items():
            for r in v:
                new_id = k+'_'+r[-1]
                results[7][new_id] = results[7][r[0]]
                # delete old entries
                if r[0] not in reps_to_del:
                    reps_to_del.add(r[0])

        for r in reps_to_del:
            del(results[7][r])

        # save updated self-scores
        self_score_file = fo.join_paths(schema_directory, ['short', 'self_scores'])
        fo.pickle_dumper(results[7], self_score_file)

        if len(novel_alleles) > 0:
            # add inferred alleles to schema
            added = add_inferred_alleles(novel_alleles, reps_info, results[2])
            print('Added {0} novel alleles to schema.'.format(added[0]))
            print('Added {0} representative alleles to schema.'.format(added[1]))
        else:
            print('No new alleles to add to schema.')

    end_time = pdt.get_datetime()

    # create output folder
    results_dir = fo.join_paths(output_directory,
                                ['results_{0}'.format(pdt.datetime_str(end_time, date_format='%Y%m%dT%H%M%S'))])
    fo.create_directory(results_dir)

    # create output files
    print('Writing logging_info.txt...', end='')
    write_logfile(start_time, end_time, len(results[1]), len(results[0]),
                  cpu_cores, blast_score_ratio, results_dir)
    print('done.')

    print('Writing results_alleles.tsv...', end='')
    write_results_alleles(list(results[0].values()),
                          list(results[1].values()), results_dir)
    print('done.')

    print('Writing results_statsitics.tsv...', end='')
    write_results_statistics(results[0], results[1], results_dir)
    print('done.')

    print('Writing loci_summary_stats.tsv...', end='')
    write_loci_summary(results[0], results_dir, len(input_files))
    print('done.')

    # list files with CDSs coordinates
    coordinates_dir = fo.join_paths(output_directory, ['temp', '2_cds_extraction'])
    coordinates_files = fo.listdir_fullpath(coordinates_dir, 'cds_hash')
    coordinates_files = {fo.file_basename(f, True).split('_cds_hash')[0]: f
                         for f in coordinates_files}
    print('Writing results_contigsInfo.tsv...', end='')
    results_contigs_outfile = write_results_contigs(list(results[0].values()), results[1],
                                                    results_dir, coordinates_files)
    print('done.')

    # determine paralogous loci and write RepeatedLoci.txt file
    print('Writing RepeatedLoci.txt...', end='')
    total_paralogous = identify_paralogous(results_contigs_outfile, results_dir)
    print('Detected number of paralog loci: {0}'.format(total_paralogous))

    if output_unclassified is True:
        create_unclassified_fasta(results[2], results[3], results[8],
                                  results[5], results_dir, results[1])

    if output_missing is True:
        create_missing_fasta(results[0], results[2], results[1], results[4],
                             results_dir, coordinates_files)

    # move file with CDSs coordinates and file with list of excluded CDSs
    cds_coordinates_source = fo.join_paths(output_directory, ['cds_info.tsv'])
    cds_coordinates_destination = fo.join_paths(results_dir, ['cds_info.tsv'])
    fo.move_file(cds_coordinates_source, cds_coordinates_destination)

    invalid_cds_source = fo.join_paths(output_directory, ['invalid_cds.txt'])
    invalid_cds_destination = fo.join_paths(results_dir, ['invalid_cds.txt'])
    # file is not created if we only search for exact matches
    if os.path.isfile(invalid_cds_source):
        fo.move_file(invalid_cds_source, invalid_cds_destination)

    # remove temporary files
    if no_cleanup is False:
        fo.delete_directory(fo.join_paths(output_directory, ['temp']))

    print('\nResults available in {0}'.format(results_dir))


def parse_arguments():

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('-i', '--input-files', nargs='?', type=str,
                        required=True, dest='input_files',
                        help='Path to the directory that contains the input '
                             'FASTA files. Alternatively, a single file with '
                             'a list of paths to FASTA files, one per line.')

    parser.add_argument('-g', '--schema-directory', type=str,
                        required=True, dest='schema_directory',
                        help='')

    parser.add_argument('-o', '--output-directory', type=str,
                        required=True, dest='output_directory',
                        help='Output directory where the process will store '
                             'intermediate files and create the schema\'s '
                             'directory.')

    parser.add_argument('--ptf', '--training-file', type=str,
                        required=False, dest='ptf_path',
                        help='Path to the Prodigal training file.')
    
    parser.add_argument('--gl', '--genes-list', type=str,
                        required=False, default=False, dest='genes_list',
                        help='Path to a file with the list of genes '
                             'in the schema that the process should '
                             'identify alleles for.')

    parser.add_argument('--bsr', '--blast-score-ratio', type=float,
                        required=False, default=0.6, dest='blast_score_ratio',
                        help='BLAST Score Ratio value. Sequences with '
                             'alignments with a BSR value equal to or '
                             'greater than this value will be considered '
                             'as sequences from the same gene.')

    parser.add_argument('--l', '--minimum-length', type=int,
                        required=False, default=201, dest='minimum_length',
                        help='Minimum sequence length value. Coding sequences '
                             'shorter than this value are excluded.')

    parser.add_argument('--t', '--translation-table', type=int,
                        required=False, default=11, dest='translation_table',
                        help='Genetic code used to predict genes and'
                             ' to translate coding sequences.')

    parser.add_argument('--st', '--size-threshold', type=float,
                        required=False, default=0.2, dest='size_threshold',
                        help='CDS size variation threshold. Added to the '
                             'schema\'s config file and used to identify '
                             'alleles with a length value that deviates from '
                             'the locus length mode during the allele calling '
                             'process.')

    parser.add_argument('--cpu', '--cpu-cores', type=int,
                        required=False, default=1, dest='cpu_cores',
                        help='Number of CPU cores that will be '
                             'used to run the CreateSchema process '
                             '(will be redefined to a lower value '
                             'if it is equal to or exceeds the total'
                             'number of available CPU cores).')

    parser.add_argument('--b', '--blast-path', type=str,
                        required=False, default='', dest='blast_path',
                        help='Path to the BLAST executables.')

    parser.add_argument('--pm', '--prodigal-mode', required=False,
                        choices=['single', 'meta'],
                        default='single', dest='prodigal_mode',
                        help='Prodigal running mode.')

    parser.add_argument('--CDS', required=False, action='store_true',
                        dest='cds_input',
                        help='If provided, input is a single or several FASTA '
                             'files with coding sequences.')

    parser.add_argument('--only-exact', required=False, action='store_true',
                        dest='only_exact',
                        help='If provided, the process will only determine '
                             'exact matches.')

    parser.add_argument('--add-inferred', required=False, action='store_true',
                        dest='add_inferred',
                        help='If provided, the process will add the sequences '
                             'of inferred alleles to the schema.')

    parser.add_argument('--no-cleanup', required=False, action='store_true',
                        dest='no_cleanup',
                        help='If provided, intermediate files generated '
                             'during process execution are not removed at '
                             'the end.')

    args = parser.parse_args()

    return args


if __name__ == "__main__":

    args = parse_arguments()
    main(**vars(args))
