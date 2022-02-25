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
import shutil
import argparse
from collections import Counter

from Bio import SeqIO

try:
    from utils import (ParalogPrunning,
                       constants as ct,
                       blast_wrapper as bw,
                       core_functions as cf,
                       file_operations as fo,
                       fasta_operations as fao,
                       process_datetime as pdt,
                       sequence_manipulation as sm,
                       iterables_manipulation as im,
                       multiprocessing_operations as mo)
except:
    from CHEWBBACA.utils import (ParalogPrunning,
                                 constants as ct,
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


###############################
# Translating everything, maybe we should only create Fasta files with distinct records
def translate_fastas(fasta_files, output_directory,
                     translation_table, cpu_cores):
    """
    """

    translation_inputs = im.divide_list_into_n_chunks(fasta_files,
                                                      len(fasta_files))

    common_args = [output_directory, translation_table]

    # add common arguments to all sublists
    translation_inputs = im.multiprocessing_inputs(translation_inputs,
                                                   common_args,
                                                   fao.translate_fasta)

    results = mo.map_async_parallelizer(translation_inputs,
                                        mo.function_helper,
                                        cpu_cores,
                                        show_progress=True)

    protein_files = {r[0]: r[1] for r in results}

    return protein_files


# input_file = f
# ids_map = {}
# output_directory = iterative_rep_dir
def select_high_score(input_file, blast_score_ratio,
                      ids_map, output_directory,
                      self_scores):
    """
    """

    # import BLASTp results
    current_results = process_blast_results(input_file,
                                            blast_score_ratio,
                                            ids_map,
                                            self_scores)

    # only save and evaluate results for loci that
    # had at least one high BSR match
    if len(current_results[0]) > 0:
        locus = fo.get_locus_id(input_file)
        current_results.append(locus)
        # save data to pickle
        pickle_out = fo.join_paths(output_directory, [locus+'_bsr'])
        fo.pickle_dumper(current_results, pickle_out)

        return pickle_out


# file = f
# sequences = all_proteins
# cds_hashtable = dna_distinct_htable
# prot_hashtable = distinct_pseqids
# cds_index = dna_cds_index
def group_by_genome(file, sequences, cds_hashtable, prot_hashtable, cds_index):
    """
    """

    high_bsr, representatives_info, locus = fo.pickle_loader(file)
    genomes_hits = [{}, representatives_info]
    for k, v in high_bsr.items():
        target_prot_hash = im.hash_sequence(sequences[k])
        target_seqids = prot_hashtable[target_prot_hash][1:]
        for g in target_seqids:
            target_dna = str(cds_index.get(g).seq)
            target_dna_len = len(target_dna)
            target_dna_hash = im.hash_sequence(target_dna)

            # get ids for all genomes with same CDS as representative
            all_genomes_with_cds = cds_hashtable[target_dna_hash][1:]
            for a in all_genomes_with_cds:
                genomes_hits[0].setdefault(a, []).append((k, target_prot_hash,
                                                          target_dna_hash, target_dna_len,
                                                          high_bsr[k]))

    return [locus, genomes_hits]


def update_classification(genome_id, locus_results, match_info,
                          multiple_classification='NIPH'):
    """
    """

    # add data about match
    locus_results.setdefault(genome_id, [match_info[3]]).append(match_info)
    # change classification if genome has multiple matches for same locus
    if len(locus_results[genome_id]) > 2:
        locus_results[genome_id][0] = multiple_classification

    return locus_results


def dna_exact_matches(fasta_file, distinct_table, locus_classifications):
    """
    """

    # read Fasta records
    sequences = fao.import_sequences(fasta_file)
    # determine SHA-256 hash for locus sequences
    sequence_hashes = {seqid: im.hash_sequence(seq)
                       for seqid, seq in sequences.items()}

    # determine locus alleles that are in inputs
    matches = {seqid.split('_')[-1]: seq_hash
               for seqid, seq_hash in sequence_hashes.items()
               if seq_hash in distinct_table}

    matches_ids = []
    total_matches = 0
    for seqid, seq_hash in matches.items():
        current_matches = distinct_table[seq_hash]
        # seqid chosen as repsentative during sequence deduplication
        distinct_seqid = current_matches[0]
        match_info = (seqid, distinct_seqid, seq_hash, 'EXC', 1.0)

        # classify as exact matches
        for gid in current_matches[1:]:
            locus_classifications = update_classification(gid, locus_classifications,
                                                          match_info, 'NIPHEM')

        # exclude element in index 0, it is the seqid chosen as
        # representative
        total_matches += len(current_matches) - 1
        # store representative id for the sequences
        matches_ids.append(current_matches[0])

    return [locus_classifications, matches_ids, total_matches]


def protein_exact_matches(fasta_file, distinct_prot_table,
                          distinct_dna_table, locus_classifications,
                          dna_index):
    """
    """

    # read Fasta records
    sequences = fao.import_sequences(fasta_file)

    # determine SHA-256 hash for locus sequences
    sequence_hashes = {seqid: im.hash_sequence(seq)
                       for seqid, seq in sequences.items()}

    # determine locus alleles that are in inputs
    matches = {seqid.split('_')[-1]: seq_hash for seqid, seq_hash in sequence_hashes.items()
               if seq_hash in distinct_prot_table}

    seen_dna = {}
    seen_prot = []
    total_cds = 0
    total_prots = 0
    total_distinct_prots = 0
    exact_prot_hashes = []
    for seqid, seq_hash in matches.items():
        # different alleles might code for the same protein
        # do not proceed if distinct protein sequence has already been seen
        if seq_hash in distinct_prot_table and seq_hash not in seen_prot:
            # get protids for distinct DNA CDSs
            protids = distinct_prot_table[seq_hash][1:]
            total_prots += len(protids)
            exact_prot_hashes.extend(protids)
            total_distinct_prots += 1
            # for each distinct CDS that codes for the protein
            for p in protids:
                cds = str(dna_index.get(p).seq)
                cds_hash = im.hash_sequence(cds)
                # get IDs of genomes that contain the CDS
                genome_ids = distinct_dna_table[cds_hash]
                total_cds += len(genome_ids) - 1
                # for each genome ID that contains the CDS
                for gid in genome_ids[1:]:
                    # first time seeing CDS
                    if cds_hash not in seen_dna:
                        # need to add inferred to locus mode values???
                        current_class = 'INF'
                        protid = seqid
                        seen_dna[cds_hash] = p
                    else:
                        current_class = 'EXC'
                        # if it matches a INF, change protid to seqid of INF
                        # that will be assigned a new allele id later
                        protid = seen_dna[cds_hash]
                    # for protein exact matches, the seqid of the translated allele,
                    # the seqid of the protein chosen as representative during sequence deduplication,
                    match_info = (protid, p, cds_hash, current_class, 1.0)
                    locus_classifications = update_classification(gid, locus_classifications,
                                                                  match_info)

            seen_prot.append(seq_hash)

    return [locus_classifications, exact_prot_hashes, total_prots,
            total_cds, total_distinct_prots]


def compute_bsr(raw_score, query_raw_score):
    """
    """

    bsr = raw_score / query_raw_score

    return bsr


# blast_output = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/test_allelecall/temp/6_iterative_reps/GCA-000427075-protein1270_blast_results_iter2.tsv'
# ids_mapping = {}
def process_blast_results(blast_output, blast_score_ratio, ids_mapping,
                          self_scores):
    """
    """

    current_results = fo.read_tabular(blast_output)

    # get allele identifier for the representative
    representatives_info = {}
    for r in current_results:
        if len(ids_mapping) > 0:
            current_id = ids_mapping[r[0]]
        else:
            current_id = r[0]
        rep_data = self_scores[current_id]
        representatives_info[current_id] = rep_data

# this might be removed later on if the alignments never include self-rep alignments

    # exclude representative self-alignment and alignments between representatives
    rep_oldies = list(set([r[0] for r in current_results]))
    current_results = [r
                       for r in current_results
                       if r[0] != r[4]
                       and r[4] not in rep_oldies]

    # get best raw score for each target
    raw_scores = {}
    for r in current_results:
        # add first ocurrence
        if r[4] not in raw_scores:
            raw_scores[r[4]] = r
        # target has >1 matches against representatives
        elif r[4] in raw_scores:
            # compare previous and current raw scores
            current_score = float(r[5])
            previous_score = float(raw_scores[r[4]][5])
            # switch match if current raw score is greater
            if current_score > previous_score:
                raw_scores[r[4]] = r

    # determine BSR values
    bsr_values = {}
    for k, v in raw_scores.items():
        if len(ids_mapping) > 0:
            current_id = ids_mapping[k]
            rep_id = ids_mapping[v[0]]
        else:
            current_id = k
            rep_id = v[0]

        bsr = compute_bsr(float(v[5]), representatives_info[rep_id][1])
        target_len = (int(v[1])-1)*3 # subtract 1 to exclude start position
        rep_len = (int(v[2])+1)*3 # add 1 to include stop codon

        # determine if representative has allele id
        try:
            int(rep_id.split('_')[-1])
            rep_id_split = rep_id.split('_')[-1]
        except Exception as e:
            # new rep that still has no allele id
            rep_id_split = rep_id

        bsr_values[current_id] = (bsr,
                                  target_len,
                                  rep_len,
                                  rep_id,
                                  rep_id_split)

    # only keep matches above BSR threshold
    high_bsr = {k: v for k, v in bsr_values.items() if v[0] >= blast_score_ratio}

    return [high_bsr, representatives_info]


def contig_position_classification(representative_length,
                                    representative_leftmost_pos,
                                    representative_rightmost_pos,
                                    contig_length,
                                    contig_leftmost_pos,
                                    contig_rightmost_pos):
    """
    """

    # careful about offset!!!
    ###########################################################
    # need to invert when necessary
    # check if this is necessary
    # match in sense strand
    if contig_rightmost_pos > contig_leftmost_pos:
        # determine rightmost aligned position in contig
        contig_rightmost_rest = contig_length - contig_rightmost_pos
        # determine leftmost aligned position in contig
        contig_leftmost_rest = contig_rightmost_pos
        # determine number of rightmost bases in the target that did not align
        representative_rightmost_rest = representative_length - representative_rightmost_pos
        # determine number of leftmost bases in the target that did not align 
        representative_leftmost_rest = representative_leftmost_pos
    # reverse values because CDS was identified in reverse strand
    elif contig_rightmost_pos < contig_leftmost_pos:
        print('PLOT!!!!!!!')
        contig_leftmost_rest = contig_rightmost_pos
        contig_rightmost_rest = contig_length - contig_leftmost_pos
        # also need to reverse values for representative
        representative_leftmost_rest = representative_rightmost_pos
        representative_rightmost_rest = representative_length - representative_leftmost_pos

    if contig_leftmost_rest < representative_leftmost_rest and contig_rightmost_rest < representative_rightmost_rest:
        return 'LOTSC'
    elif contig_leftmost_rest < representative_leftmost_rest:
        return 'PLOT3'
    elif contig_rightmost_rest < representative_rightmost_rest:
        return 'PLOT5'


def allele_size_classification(target_dna_len, locus_mode, size_threshold):
    """
    """

    if target_dna_len < (locus_mode[0]-(locus_mode[0])*size_threshold):
        return 'ASM'
    elif target_dna_len > (locus_mode[0]+(locus_mode[0])*size_threshold):
        return 'ALM'


# locus = 'GCA-000007265-protein1068'
# genomes_matches = [c[1] for c in classification_inputs if c[0] == locus][0]
# representatives_info = [c[2] for c in classification_inputs if c[0] == locus][0]
# inv_map = [c[3] for c in classification_inputs if c[0] == locus][0]
# contigs_lengths = [c[4] for c in classification_inputs if c[0] == locus][0]
# locus_results_file = [c[5] for c in classification_inputs if c[0] == locus][0]
# locus_mode = [c[6] for c in classification_inputs if c[0] == locus][0]
# temp_directory = [c[7] for c in classification_inputs if c[0] == locus][0]
# size_threshold = [c[8] for c in classification_inputs if c[0] == locus][0]
# blast_score_ratio = [c[9] for c in classification_inputs if c[0] == locus][0]
def classify_inexact_matches(locus, genomes_matches, representatives_info,
                             inv_map, contigs_lengths, locus_results_file,
                             locus_mode, temp_directory, size_threshold,
                             blast_score_ratio):
    """
    """

    locus_results = fo.pickle_loader(locus_results_file)

    # initialize lists to store hashes of CDSs that have been classified
    seen_dna = {}
    seen_prot = []
    # initialize list to store sequence identifiers that have been classified
    excluded = []
    representative_candidates = []
    for genome, matches in genomes_matches.items():
        current_g = inv_map[genome]
        contig_lengths = contigs_lengths[current_g]

        # open pickle for genome and get coordinates
        genome_cds_file = fo.join_paths(temp_directory, ['2_cds_extraction', current_g+'_cds_hash'])
        genome_cds_coordinates = fo.pickle_loader(genome_cds_file)
        for m in matches:
            # get sequence identifier for the representative CDS
            target_seqid = m[0]
            # get allele identifier for the schema representative
            rep_alleleid = m[4][4]
            # get hash of the CDS DNA sequence
            target_dna_hash = m[2]
            # get hash of the translated CDS sequence
            target_prot_hash = m[1]

            # get the BSR value
            bsr = m[4][0]

            # # store sequence identifiers that have been classified
            # excluded.append(target_seqid)

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

                # excluded.append(target_seqid)
                # print(genome, m, 'PROT')
                continue

            # only proceed if there are no representative candidates
            # this way we can classify exact matches after finding a representative
            # but will not determine new reps without aligning against the one that was discovered
            # this might add wrong representative id to locus results if match is against new representative...
            if len(representative_candidates) == 0:
                # there is no DNA or Protein exact match, perform full evaluation
    
                # classifications based on position on contig (PLOT3, PLOT5 and LOTSC)
                # get CDS start and stop positions
                genome_coordinates = genome_cds_coordinates[target_dna_hash][0]
                contig_leftmost_pos = int(genome_coordinates[1])
                contig_rightmost_pos = int(genome_coordinates[2])
                # get contig length
                contig_length = contig_lengths[genome_coordinates[0]]
                # get representative length
                representative_length = representatives_info[m[4][3]][0]
                # get target left and right positions that aligned
                representative_leftmost_pos = m[4][1]
                representative_rightmost_pos = m[4][2]
                # determine if it is PLOT3, PLOT5 or LOTSC
                relative_pos = contig_position_classification(representative_length,
                                                              representative_leftmost_pos,
                                                              representative_rightmost_pos,
                                                              contig_length,
                                                              contig_leftmost_pos,
                                                              contig_rightmost_pos)
    
                if relative_pos is not None:
                    locus_results = update_classification(genome, locus_results,
                                                          (rep_alleleid, target_seqid,
                                                           target_dna_hash, relative_pos, bsr))
                    # need to exclude so that it does not duplicate ASM/ALM classifications later
                    excluded.append(target_seqid)
                    continue
    
                target_dna_len = m[3]
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
                #print(genome, m, 'INF')
                seen_prot.append(target_prot_hash)

        # update locus mode value if classification for genome is INF
        ### this is not being updated properly if a INF case turns into NIPH
        ### the NIPH class will not allow for the INF length to be added and
        ### the next match to the INF will be stored as EXC
        if genome in locus_results and locus_results[genome][0] == 'INF':
            # append length of inferred allele to list with allele sizes
            locus_mode[1].append(target_dna_len)
            # compute mode
            locus_mode[0] = sm.determine_mode(locus_mode[1])[0]
            # only add as representative candidate if classification is not NIPH
            inf_bsr = locus_results[genome][1][4]
            if inf_bsr >= blast_score_ratio and inf_bsr < blast_score_ratio+0.1:
                representative_candidates.append((genome, target_seqid,
                                                  m[4][3], target_dna_hash))

    # save updated results
    fo.pickle_dumper(locus_results, locus_results_file)

    return {locus: [locus_results_file, locus_mode,
                    excluded, representative_candidates]}


# classification_files = results[0]
# locus = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/sagalactiae32_schema/schema_seed/GCA-000007265-protein50.fasta'
# results = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/test_allelecall/temp/3_cds_preprocess/GCA-000007265-protein50_results'
def assign_ids(classification_files, schema_directory):
    """
    """

    # assign allele identifiers
    new_alleles = {}
    #novel_ids = {}
    for locus, results in classification_files.items():
        locus_id = fo.get_locus_id(locus)
        # get loci records
        records = fao.import_sequences(locus)
        # get id of max record
        max_alleleid = max([int(rec.split('_')[-1]) for rec in records])
        locus_results = fo.pickle_loader(results)
        # iterate and assign allele identifiers
        seen = {}
        # sort to get INF classifications first
        sorted_r = sorted(locus_results.items(),
                          key=lambda x: x[1][0] == 'INF',
                          reverse=True)

        for k in sorted_r:
            genome_id = k[0]
            current_results = k[1]
            cds_hash = current_results[1][2]
            
            # try:
            #     int(current_results[1][0])
            #     allele_id = current_results[1][0]
            # except Exception as e:
            #     allele_id = novel_ids[current_results[1][0]]

            if current_results[0] == 'EXC':
                #locus_results[genome_id].append(current_results[1][0])
                try:
                    int(current_results[1][0])
                    locus_results[genome_id].append(current_results[1][0])
                except Exception as e:
                    locus_results[genome_id].append(seen[cds_hash])
            elif current_results[0] == 'EXCP':
                # this should be True every single case, but INF cases might be converted
                # to NIPH due to a second match after being used to detect EXCP
                if cds_hash in seen:
                    locus_results[genome_id].append(seen[cds_hash])
                # the exact match might not be found because the INF that
                # added the match was converted to NIPH
                # we need to add the new allele based on the EXCP case...
                else:
                    max_alleleid += 1
                    locus_results[genome_id].append('INF-{0}'.format(max_alleleid))
                    seen[cds_hash] = str(max_alleleid)
                    # add the unique SHA256 value (if we add the seqid we might get a seqid that does not match the hash
                    # during the iterative classification step with the representatives we can add the wrong seqid)
                    new_alleles.setdefault(locus, []).append([current_results[1][2], str(max_alleleid)])
                    #novel_ids[current_results[1][1]] = str(max_alleleid)
            elif current_results[0] == 'INF':
                if cds_hash not in seen:
                    max_alleleid += 1
                    locus_results[genome_id].append('INF-{0}'.format(max_alleleid))
                    seen[cds_hash] = str(max_alleleid)
                    # add the unique SHA256 value (if we add the seqid we might get a seqid that does not match the hash
                    # during the iterative classification step with the representatives we can add the wrong seqid)
                    new_alleles.setdefault(locus, []).append([current_results[1][2], str(max_alleleid)])
                    #novel_ids[current_results[1][1]] = str(max_alleleid)
                else:
                    print('INF case was already seen!')
                    locus_results[genome_id].append(seen[cds_hash])

        # save updated info
        fo.pickle_dumper(locus_results, results)

    return new_alleles


# inferred_alleles_data = new_alleles
# new_reps = reps_info
# sequences_file = results[2]
def add_inferred_alleles(inferred_alleles_data, new_reps, sequences_file):
    """
    """

    # create index for Fasta file with distinct CDSs
    sequence_index = SeqIO.index(sequences_file, 'fasta')

    # count number of inferred alleles added to schema
    total_inferred = 0
    total_representative = 0
    for locus_path, inferred_alleles in inferred_alleles_data.items():
        locus_id = fo.get_locus_id(locus_path)

        # get novel alleles through indexed Fasta file
        inferred_sequences = [('{0}_{1}'.format(locus_id, a[1]),
                               str(sequence_index.get(a[2]).seq))
                              for a in inferred_alleles]

        total_inferred += len(inferred_sequences)

        updated_lines = ['>{0}\n{1}'.format(a[0], a[1]) for a in inferred_sequences]
        fo.write_lines(updated_lines, locus_path, write_mode='a')

        # add representatives
        locus_new_reps = new_reps.get(locus_id, None)
        if locus_new_reps is not None:
            reps_sequences = [('{0}_{1}'.format(locus_id, a[2]),
                               str(sequence_index.get(a[0]).seq))
                              for a in locus_new_reps]

            total_representative += len(reps_sequences)

            updated_lines = ['>{0}\n{1}'.format(a[0], a[1]) for a in reps_sequences]
            locus_short_path = os.path.join(os.path.dirname(locus_path), 'short', locus_id+'_short.fasta')
            fo.write_lines(updated_lines, locus_short_path, write_mode='a')

    return [total_inferred, total_representative]


def write_logfile(start_time, end_time, total_inputs,
                  total_loci, cpu_cores, blast_score_ratio,
                  output_directory):
    """
    """

    start_time_str = pdt.datetime_str(start_time,
                                      date_format='%Y-%m-%d - %H:%M:%S')

    end_time_str = pdt.datetime_str(end_time,
                                    date_format='%Y-%m-%d - %H:%M:%S')

    log_outfile = fo.join_paths(output_directory, ['logging_info.txt'])
    logfile_text = ct.LOGFILE_TEMPLATE.format(start_time_str, end_time_str,
                                              total_inputs,total_loci,
                                              cpu_cores, blast_score_ratio)
    with open(log_outfile, 'w') as outfile:
        outfile.write(logfile_text)

    return log_outfile


def write_results_alleles(classification_files, input_identifiers,
                          output_directory):
    """
    """

    # add first column with input identifiers
    columns = [['FILE'] + input_identifiers]
    for file in classification_files.values():
        locus_id = fo.get_locus_id(file)
        locus_results = fo.pickle_loader(file)
        locus_column = [locus_id]
        for i in range(1, len(input_identifiers)+1):
            if i in locus_results:
                current_result = locus_results[i]
                # exact or inferred
                if current_result[0] in ['EXC', 'EXCP', 'INF']:
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

    output_file = fo.join_paths(output_directory, ['results_alleles.tsv'])
    fo.write_lines(lines, output_file)


def write_results_statistics(classification_files, input_identifiers,
                             output_directory):
    """
    """

    # initialize classification counts per input
    input_classifications = {i: [] for i in range(1, len(input_identifiers)+1)}
    for file in classification_files.values():
        locus_id = fo.get_locus_id(file)
        locus_results = fo.pickle_loader(file)

        for i in range(1, len(input_identifiers)+1):
            input_classifications[i].append(locus_results.get(i, ['LNF'])[0])

    # determine class counts per input
    class_counts = {i: Counter(v) for i, v in input_classifications.items()}
    # add exact matches after inferring new allele based on protein exact match
    for k, v in class_counts.items():
        class_counts[k]['EXC'] += class_counts[k]['EXCP']
        # add zero for remaining classes
        class_counts[k].update({c: 0
                                for c in ct.ALLELECALL_CLASSIFICATIONS
                                if c not in v})

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


def write_results_contigs(classification_files, identifiers, output_directory,
                          cds_coordinates_files):
    """
    """

    invalid_classes = ct.ALLELECALL_CLASSIFICATIONS[2:]

    columns = [['FILE'] + identifiers]
    for file in classification_files.values():
        locus_id = fo.get_locus_id(file)
        locus_results = fo.pickle_loader(file)
        column = [locus_id]
        # get sequence hash for exact and inferred
        # get classification for other cases
        column += [locus_results[i][1][2]
                   if i in locus_results and locus_results[i][0] not in invalid_classes
                   else locus_results.get(i, ['LNF'])[0]
                   for i in range(1, len(identifiers)+1)]

        columns.append(column)

    # group elements with same list index
    lines = im.aggregate_iterables(columns)

    final_lines = [lines[0]]
    for l in lines[1:]:
        genome_id = l[0]
        # open file with loci coordinates
        coordinates = fo.pickle_loader(cds_coordinates_files[genome_id])
        new_line = [coordinates[c][0] if c in coordinates else c for c in l[1:]]

        new_line = ['{0}&{1}-{2}&{3}'.format(*c)
                    if c not in invalid_classes else c
                    for c in new_line]

        final_lines.append([genome_id]+new_line)

    #########################
    # Start positions have offset of 1 and do not match start positions reported by previous implementation?
    #########################

    # write file
    output_file = fo.join_paths(output_directory, ['results_contigsInfo.tsv'])
    final_lines = ['\t'.join(l) for l in final_lines]
    fo.write_lines(final_lines, output_file)
    
    return output_file


def aggregate_blast_results(blast_files, output_directory, ids_dict):
    """
    """

    # group files for representatives of the same locus
    loci_results = {}
    for f in blast_files:
        locus_rep = ids_dict[im.match_regex(f, r'seq_[0-9]+')]
        locus_id = im.match_regex(locus_rep, r'^.+-protein[0-9]+')
        loci_results.setdefault(locus_id, []).append(f)

    # concatenate results for representatives of the same locus
    concatenated_files = []
    concatenate_file_template = '{0}.concatenated_blastout.tsv'
    for locus, files in loci_results.items():
        outfile = fo.join_paths(output_directory,
                                [concatenate_file_template.format(locus)])
        fo.concatenate_files(files, outfile)
        concatenated_files.append(outfile)

    return concatenated_files


def count_classifications(classification_files):
    """
    """

    global_counts = Counter()
    # get total number of classified CDSs
    total_cds = 0
    for file in classification_files.values():
        locus_results = fo.pickle_loader(file)
        total_cds += sum([len(c)-1 for g, c in locus_results.items()])
        all_classifications = [c[0] for g, c in locus_results.items()]
        locus_counts = Counter(all_classifications)
        global_counts += locus_counts

    # add protein exact matches to exact matches count
    global_counts['EXC'] += global_counts['EXCP']
    del global_counts['EXCP']

    # add classification that might be missing
    global_counts.update(Counter({k: 0 for k in ct.ALLELECALL_CLASSIFICATIONS
                         if k not in global_counts}))

    return [global_counts, total_cds]


# start_time = pdt.get_datetime()
# end_time = pdt.get_datetime()
def write_outputs(classification_files, inv_map, output_directory,
                   start_time, end_time, cpu_cores, blast_score_ratio):
    """
    """

    input_identifiers = [inv_map[i] for i in range(1, len(inv_map)+1)]

    # create output folder
    results_dir = fo.join_paths(output_directory,
                                ['results_{0}'.format(end_time)])
    fo.create_directory(results_dir)

    print('Writing logging_info.txt...', end='')
    write_logfile(start_time, end_time, len(inv_map), len(classification_files),
                  cpu_cores, blast_score_ratio, results_dir)
    print('done.')

    # create results_alleles.tsv
    print('Writing results_alleles.tsv...', end='')
    write_results_alleles(classification_files, input_identifiers, results_dir)
    print('done.')

    # create results_statsitics.tsv
    print('Writing results_statsitics.tsv...', end='')
    write_results_statistics(classification_files, inv_map, results_dir)
    print('done.')

    # create results_contigsInfo.tsv
    # using too much memory???
    # list files with CDSs coordinates
    # move folder names to file with constants?
    coordinates_dir = fo.join_paths(output_directory, ['temp', '2_cds_extraction'])
    coordinates_files = fo.listdir_fullpath(coordinates_dir, 'cds_hash')
    coordinates_files = {fo.file_basename(f, True).split('_cds_hash')[0]: f
                         for f in coordinates_files}
    print('Writing results_contigsInfo.tsv...', end='')
    results_contigs_outfile = write_results_contigs(classification_files, input_identifiers,
                                                    results_dir, coordinates_files)
    print('done.')

    # determine paralogous loci and write RepeatedLoci.txt file
    print('Writing RepeatedLoci.txt...', end='')
    ParalogPrunning.main(results_contigs_outfile, results_dir)

    print('\nResults available in {0}'.format(results_dir))

    return results_dir


def create_classification_file(locus_id, output_directory):
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

    Return
    ------
    pickle_out : str
        Path to the file created to store classification
        results.
    """

    empty_results = {}
    pickle_out = fo.join_paths(output_directory,
                               [locus_id+'_results'])

    # create file with empty results structure
    fo.pickle_dumper(empty_results, pickle_out)

    return pickle_out


#input_files = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/ids.txt'
input_files = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/ids32.txt'
output_directory = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/test_allelecall'
ptf_path = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/sagalactiae32_schema/schema_seed/Streptococcus_agalactiae.trn'
blast_score_ratio = 0.6
minimum_length = 201
translation_table = 11
size_threshold = 0.2
word_size = 5
window_size = 5
clustering_sim = 0.2
representative_filter = 0.9
intra_filter = 0.9
cpu_cores = 6
blast_path = '/home/rfm/Software/anaconda3/envs/spyder/bin'
prodigal_mode = 'single'
cds_input = False
only_exact = False
schema_directory = '/home/rfm/Desktop/rfm/Lab_Software/AlleleCall_tests/sagalactiae32_schema/schema_seed'
add_inferred = True
no_cleanup = True
def allele_calling(input_files, schema_directory, output_directory, ptf_path,
                   blast_score_ratio, minimum_length, translation_table,
                   size_threshold, word_size, window_size, clustering_sim,
                   cpu_cores, blast_path, prodigal_mode, cds_input,
                   only_exact):
    """
    """

    # define directory for temporary files
    temp_directory = fo.join_paths(output_directory, ['temp'])
    fo.create_directory(temp_directory)

    # read file with paths to input files
    fasta_files = fo.read_lines(input_files, strip=True)

    # sort paths to FASTA files
    fasta_files = im.sort_iterable(fasta_files, sort_key=str.lower)

    # map full paths to basename
    inputs_basenames = im.mapping_function(fasta_files,
                                           fo.file_basename, [False])

    # map input identifiers to integers
    # use the mapped integers to refer to each input
    # this reduces memory usage compared to using string identifiers
    map_ids = im.integer_mapping(inputs_basenames.values())
    inv_map = im.invert_dictionary(map_ids)

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
    print('\nRemoving duplicated DNA sequences...', end='')
    distinct_dna_template = 'distinct_cds_{0}.fasta'
    dna_dedup_results = cf.exclude_duplicates(cds_files, preprocess_dir,
                                              cpu_cores, distinct_dna_template,
                                              map_ids, False)

    dna_distinct_htable, distinct_file, repeated = dna_dedup_results
    print('removed {0} sequences.'.format(repeated))

    # get list of loci files
    print('Getting list of loci...', end='')
    loci_files = fo.listdir_fullpath(schema_directory,
                                     substring_filter='.fasta')

    # get mapping between locus file path and locus identifier
    loci_basenames = im.mapping_function(loci_files, fo.file_basename, [False])
    print('schema has {0} loci.'.format(len(loci_files)))

    # create files with empty results data structure
    inputs = [[loci_basenames[file], preprocess_dir] for file in loci_files]
    classification_files = {file: create_classification_file(*inputs[i])
                            for i, file in enumerate(loci_files)}

    print('Finding DNA exact matches...', end='')
    dna_exact_hits = 0
    dna_matches_ids = []
    for locus, results_file in classification_files.items():
        locus_classifications = fo.pickle_loader(results_file)
        em_results = dna_exact_matches(locus, dna_distinct_htable, locus_classifications)
        # save updated classifications
        fo.pickle_dumper(em_results[0], results_file)
        # extend list of matched seqids
        dna_matches_ids.extend(em_results[1])
        dna_exact_hits += em_results[2]

    print('found {0} exact matches (matching {1} alleles).'
          ''.format(dna_exact_hits, len(dna_matches_ids)))

    current_counts, current_cds = count_classifications(classification_files)
    print(current_counts, current_cds)

    after_dna_exact = fo.pickle_loader(preprocess_dir+'/GCA-000007265-protein1_results')

    # user only wants to determine exact matches
    if only_exact is True:
        # return classification files for creation of output files
        return [classification_files, inv_map, []]

    # create new Fasta file without the DNA sequences that were exact matches
    dna_index = SeqIO.index(distinct_file, 'fasta')
    unique_fasta = fo.join_paths(preprocess_dir, ['dna_non_exact.fasta'])
    # this step is taking too long? Is it also using too much memory?
    # Optimize to run faster with a great number of input assemblies!
    # multiprocessing? iterate over generator instead?
    total_selected = fao.exclude_sequences_by_id(dna_index,
                                                 dna_matches_ids,
                                                 unique_fasta)

    # verify if having these identifiers in memory is problematic for huge datasets
    # this also takes some time to run...
    selected_ids = [rec for rec in dna_index if rec not in dna_matches_ids]

    # translate DNA sequences and identify duplicates
    print('\nTranslating {0} DNA sequences...'.format(total_selected))

    # this step excludes small sequences
    ts_results = cf.translate_sequences(selected_ids, unique_fasta,
                                        preprocess_dir, translation_table,
                                        minimum_length, cpu_cores)

    dna_file, protein_file, ut_seqids, ut_lines = ts_results

    print('Removed {0} DNA sequences that could not be '
          'translated.'.format(len(ut_seqids)))

    # write info about invalid alleles to file
    invalid_alleles_file = fo.join_paths(output_directory,
                                         ['invalid_cds.txt'])
    invalid_alleles = im.join_list(ut_lines, '\n')
    fo.write_to_file(invalid_alleles, invalid_alleles_file, 'w', '\n')
    print('Info about untranslatable and small sequences '
          'stored in {0}'.format(invalid_alleles_file))

    # protein sequences deduplication step
    # we can add multiprocessing to this step if the function that translates does not concatenate the files with translated sequences
    print('\nRemoving duplicated protein sequences...', end='')
    distinct_prot_template = 'distinct_prots_{0}.fasta'
    ds_results = cf.exclude_duplicates([protein_file], preprocess_dir, 1,
                                       distinct_prot_template, map_ids, True)
    print('removed {0} sequences.'.format(ds_results[2]))
    distinct_pseqids = ds_results[0]

    # translate loci files
    print('Translating schema alleles...')
    protein_dir = os.path.join(temp_directory, '4_protein_dir')
    fo.create_directory(protein_dir)
    # alleles that code for the same protein will be represented several times. Is it problematic?
    protein_files = translate_fastas(loci_files, protein_dir,
                                     translation_table, cpu_cores)

    # identify exact matches at protein level
    # exact matches are novel alleles that can be added to the schema
    # this reports a huge number for the dataset with 320 genomes. Is it normal?
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
                                           dna_index)

        fo.pickle_dumper(em_results[0], results_file)
        exact_phashes.extend(em_results[1])
        exc_prot += em_results[2]
        # this reports a huge number for the dataset with 320 genomes. Is it normal?
        exc_cds += em_results[3]
        exc_distinct_prot += em_results[-1]

    # need to determine number of distinct proteins to print correct info!!!
    print('found {0} protein exact matches (matching {1} distinct proteins).'
          ''.format(exc_prot, exc_distinct_prot))

    # this reports a huge number for the dataset with 320 genomes. Is it normal?
    print('Protein matches correspond to {0} DNA matches.'.format(exc_cds))

    current_counts, current_cds = count_classifications(classification_files)
    print(current_counts, current_cds)

    after_prot_exact = fo.pickle_loader(preprocess_dir+'/GCA-000007265-protein1_results')

    # create new Fasta file without the Protein sequences that were exact matches
    unique_pfasta = fo.join_paths(preprocess_dir, ['protein_non_exact.fasta'])
    # create protein file index
    protein_index = SeqIO.index(ds_results[1], 'fasta')
    # the list of "exact_phases" corresponds to the seqids for the DNA sequences
    # this means that it can have more elements that the number of protein exact matches
    # because the different alleles might code for same protein
    total_selected = fao.exclude_sequences_by_id(protein_index, exact_phashes, unique_pfasta)

    # translate schema representatives
    print('Translating schema representatives...')
    rep_dir = os.path.join(schema_directory, 'short')
    rep_list = fo.listdir_fullpath(rep_dir, '.fasta')
    protein_repfiles = translate_fastas(rep_list, protein_dir,
                                        translation_table, cpu_cores)
    protein_repfiles = list(protein_repfiles.values())

    # cluster protein sequences
    proteins = fao.import_sequences(unique_pfasta)

    # create directory to store clustering data
    clustering_dir = fo.join_paths(temp_directory, ['5_clustering'])
    fo.create_directory(clustering_dir)

    # define BLASTp and makeblastdb paths
    blastp_path = os.path.join(blast_path, ct.BLASTP_ALIAS)
    makeblastdb_path = os.path.join(blast_path, ct.MAKEBLASTDB_ALIAS)

    # concatenate all schema representative
    concat_reps = os.path.join(protein_dir, 'concat_reps.fasta')
    fo.concatenate_files(protein_repfiles, concat_reps)

    # determine self-score for representatives if file is missing
    self_score_file = fo.join_paths(schema_directory, ['short', 'self_scores'])
    if os.path.isfile(self_score_file) is False:
        # change identifiers to shorten and avoid BLASTp error?
        blast_db = fo.join_paths(temp_directory, ['representatives'])
        # will not work if file contains duplicates
        db_stderr = bw.make_blast_db(makeblastdb_path, concat_reps,
                                     blast_db, 'prot')

        output_blast = fo.join_paths(temp_directory, ['representatives_blastout.tsv'])
        blastp_stderr = bw.run_blast(blastp_path, blast_db, concat_reps,
                                    output_blast, threads=cpu_cores)

        current_results = fo.read_tabular(output_blast)
        # get raw score and sequence length
        self_scores = {l[0]: ((int(l[3])*3)+3, float(l[-1]))
                       for l in current_results
                       if l[0] == l[4]}

        fo.pickle_dumper(self_scores, self_score_file)
    # import data for representatives
    else:
        self_scores = fo.pickle_loader(self_score_file)

    # create index for representative sequences
    rep_proteins = fao.import_sequences(concat_reps)

    # create Kmer index for representatives
    representatives = im.kmer_index(rep_proteins, 5)[0]
    # cluster CDSs into representative clusters
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
        all_prots = os.path.join(blasting_dir, 'all_prots.fasta')

        # create Fasta file with remaining proteins and representatives
        fo.concatenate_files([unique_pfasta, concat_reps], all_prots)

        all_proteins = fao.import_sequences(all_prots)

        # BLAST clustered sequences against cluster representatives
        blast_results, ids_dict = cf.blast_clusters(clusters, all_proteins,
                                                    blasting_dir, blastp_path,
                                                    makeblastdb_path, cpu_cores,
                                                    'blast', True)

        blast_files = im.flatten_list(blast_results)

    concatenated_files = aggregate_blast_results(blast_files, clustering_dir, ids_dict)

    # import results and determine BSR
    high_scoring = []
    for f in concatenated_files:
        # exclude results in the BSR+0.1 threshold
        # process representative candidates in later stage
        outfile = select_high_score(f, blast_score_ratio+0.1,
                                    ids_dict, clustering_dir,
                                    self_scores)
        if outfile is not None:
            high_scoring.append(outfile)

    # create index for distinct CDS DNA sequences
    dna_cds_index = SeqIO.index(unique_fasta, 'fasta')
    # create index for distinct protein sequences
    prot_index = SeqIO.index(all_prots, 'fasta')

    # group results for each locus per genome
    loci_results = {}
    for f in high_scoring:
        results = group_by_genome(f, all_proteins, dna_distinct_htable,
                                  distinct_pseqids, dna_cds_index)
        loci_results[results[0]] = results[1]

    # get contig length for all genomes
    contigs_lengths = {inputs_basenames[f]: fao.sequences_lengths(f)
                       for f in fasta_files}

    # determine size mode for each locus
    print('\nDetermining sequence length mode for all loci...', end='')
    loci_modes = {}
    for file in loci_files:
        alleles_sizes = list(fao.sequences_lengths(file).values())
        loci_modes[loci_basenames[file]] = [sm.determine_mode(alleles_sizes)[0], alleles_sizes]

    print('done.')

    # process results per genome and per locus
    print('Classification...')
    classification_inputs = []
    for locus, hits in loci_results.items():
        genomes_matches, representatives_info = hits

        # get locus length mode
        locus_mode = loci_modes[locus]

        # import file with locus classifications
        locus_results_file = fo.join_paths(preprocess_dir, [locus+'_results'])
        
        classification_inputs.append([locus, genomes_matches,
                                      representatives_info,
                                      inv_map, contigs_lengths,
                                      locus_results_file, locus_mode,
                                      temp_directory, size_threshold,
                                      blast_score_ratio,
                                      classify_inexact_matches])

    class_results = mo.map_async_parallelizer(classification_inputs,
                                              mo.function_helper,
                                              cpu_cores,
                                              show_progress=True)

    after_cluster = fo.pickle_loader(preprocess_dir+'/GCA-000007265-protein1_results')
    after_cluster2 = fo.pickle_loader(preprocess_dir+'/GCA-000007265-protein1068_results')
    after_cluster3 = fo.pickle_loader(preprocess_dir+'/GCA-000007265-protein977_results')

    excluded = []
    for r in class_results:
        locus = list(r.keys())[0]
        results = r[locus]
        # this does not include the length of alleles inferred through protein exact matches
        loci_modes[locus] = results[1]
        excluded.extend(results[2])

    # may have repeated elements due to same CDS matching different loci
    excluded = set(excluded)
    print('\nExcluded distinct proteins: {0}'.format(len(excluded)))

    # get seqids of remaining unclassified sequences
    unclassified_ids = [rec.id
                        for rec in SeqIO.parse(unique_pfasta, 'fasta')
                        if rec.id not in excluded]
    print('Remaining: {0}'.format(len(unclassified_ids)))

    # get seqids of schema representatives
    reps_ids = [rec.id for rec in SeqIO.parse(concat_reps, 'fasta')]
    print('Schema has a total of {0} representative alleles.'
          ''.format(len(reps_ids)))

    # create directory to store data for each iteration
    iterative_rep_dir = fo.join_paths(temp_directory, ['6_iterative_reps'])
    fo.create_directory(iterative_rep_dir)

    # BLAST schema representatives against remaining unclassified CDSs
    new_reps = {}
    iteration = 1
    exausted = False
    # keep iterating while new representatives are discovered
    while exausted is False:
        remaining_seqs_file = fo.join_paths(iterative_rep_dir,
                                            ['remaining_prots_iter{0}.fasta'.format(iteration)])
        # create Fasta with unclassified sequences
        fao.get_sequences_by_id(prot_index, unclassified_ids,
                                remaining_seqs_file, limit=50000)

        # print info about number of unclassified CDSs

        # shorten ids to avoid BLASTp error?
        blast_db = fo.join_paths(iterative_rep_dir, ['blastdb_iter{0}'.format(iteration)])
        # will not work if file contains duplicated seqids
        db_stderr = bw.make_blast_db(makeblastdb_path, remaining_seqs_file,
                                     blast_db, 'prot')

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
            outfile = fo.join_paths(iterative_rep_dir,
                                    [locus_id+'_blast_results_iter{0}.tsv'.format(iteration)])
            output_files.append(outfile)

            blast_inputs.append([blastp_path, blast_db, file, outfile,
                                 1, 1, bw.run_blast])

        # BLAST representatives against unclassified sequences
        print('BLASTing...\n')
        blastp_results = mo.map_async_parallelizer(blast_inputs,
                                                   mo.function_helper,
                                                   cpu_cores,
                                                   show_progress=True)

        # prepare results for allele calling
        high_scoring = []
        for f in output_files:
            outfile = select_high_score(f, blast_score_ratio,
                                        {}, iterative_rep_dir,
                                        self_scores)
            if outfile is not None:
                high_scoring.append(outfile)

        # group by input genome
        loci_results = {}
        for f in high_scoring:
            results = group_by_genome(f, all_proteins, dna_distinct_htable,
                                      distinct_pseqids, dna_cds_index)
            loci_results[results[0]] = results[1]

        # possible to have several representative candidates per locus
        # we must pick one to be a new representative and re-evaluate
        # the remaining candidates because they might share a BSR > 0.7
        # with the new representative
        reps_to_repeat = {}
        for k, v in loci_results.items():
            matches = {}
            genomes_matched = []
            for g, m in v[0].items():
                # new prot hash and BSR < 0.7
                if m[0][1] not in matches and m[0][4][0] < 0.7:
                    matches[m[0][1]] = m[0][4][0]
                    genomes_matched.append(g)

            if len(matches) > 1:
                reps_to_repeat.setdefault(k, []).append(v[1])
                # remove entries from other candidates so that
                # they are not classified
                for i in genomes_matched[1:]:
                    del(loci_results[k][0][i])

        print('\nLoci with new hits: '
              '{0}'.format(len(loci_results)))

        if len(loci_results) == 0:
            exausted = True
            continue

        # process results per genome and per locus
        print('Classification...')
        classification_inputs = []
        for locus, hits in loci_results.items():
            genomes_matches, representatives_info = hits

            # get locus length mode
            locus_mode = loci_modes[locus]

            # import file with locus classifications
            locus_results_file = fo.join_paths(preprocess_dir, [locus+'_results'])

            classification_inputs.append([locus, genomes_matches,
                                          representatives_info,
                                          inv_map, contigs_lengths,
                                          locus_results_file, locus_mode,
                                          temp_directory, size_threshold,
                                          blast_score_ratio,
                                          classify_inexact_matches])

        class_results = mo.map_async_parallelizer(classification_inputs,
                                                  mo.function_helper,
                                                  cpu_cores,
                                                  show_progress=True)

        after_iter = fo.pickle_loader(preprocess_dir+'/GCA-000007265-protein977_results')

        # may have repeated elements due to same CDS matching different loci
        excluded = []
        representative_candidates = {}
        for r in class_results:
            locus = list(r.keys())[0]
            results = r[locus]
            loci_modes[locus] = results[1]
            excluded.extend(results[2])
            if len(results[3]) > 0:
                representative_candidates[locus] = results[3]

        print('\nSelecting representatives for next iteration.')

        # should only have 1 representative candidate per locus because
        # classification stops when a new representative is found        
        representatives = {k: (v[0][1], v[0][3])
                           for k, v in representative_candidates.items()}

        for k, v in representatives.items():
            new_reps.setdefault(k, []).append(v)

        # remove representative candidates ids from excluded
        excluded = set(excluded) - set([v[0] for k, v in representatives.items()])

        # include new representatives
        print('Classified {0} proteins.'.format(len(excluded)+len(representatives)))

        # exclude sequences that were excluded
        unclassified_ids = set(unclassified_ids) - excluded

        # exclude representatives too because all alleles that are equal were classified
        # we may have repeated representatives because they matched several loci
        representative_ids = [l[0] for l in list(representatives.values())]
        unclassified_ids = list(unclassified_ids - set(representative_ids))
        # new representatives and alleles that amtch in other genomes should have been all classified
        print('Remaining unclassified proteins: {0}'.format(len(unclassified_ids)))

        # stop iterating if it is not possible to identify representatives
        if len(representatives) == 0:
            exausted = True
        else:
            iteration += 1
            # create files with representative sequences
            # need to include previous reps if all matches were not >= 0.7
            reps_ids = []
            protein_repfiles = []
            for k, v in representatives.items():
                # get new representative for locus
                # only getting one rep
                current_new_rep = v[0]
                reps_ids.append(current_new_rep)

                # add previous representatives that had multiple BSR < 0.7 matches
                current_previous_reps = reps_to_repeat.get(k, None)
                if current_previous_reps is not None:
                    current_previous_reps = [list(r.keys()) for r in current_previous_reps]
                    current_previous_reps = im.flatten_list(current_previous_reps)
                else:
                    current_previous_reps = []

                current_rep_ids = [current_new_rep]+current_previous_reps

                rep_file = fo.join_paths(iterative_rep_dir,
                                         ['{0}_reps_iter{1}.fasta'.format(k, iteration)])
                fao.get_sequences_by_id(prot_index, current_rep_ids, rep_file)
                protein_repfiles.append(rep_file)
                #print(rep_file, len(current_rep_ids))

            # determine self-score for new reps
            # concatenate reps
            concat_repy = fo.join_paths(iterative_rep_dir, ['{0}_concat_reps.fasta'.format(iteration)])
            fao.get_sequences_by_id(prot_index, set(reps_ids), concat_repy, limit=50000)

            blast_db = fo.join_paths(iterative_rep_dir, ['representatives_{0}'.format(iteration)])
            # will not work if file contains duplicates
            db_stderr = bw.make_blast_db(makeblastdb_path, concat_repy,
                                         blast_db, 'prot')

            output_blast = fo.join_paths(iterative_rep_dir, ['representatives_blastout_{0}.tsv'.format(iteration)])
            blastp_stderr = bw.run_blast(blastp_path, blast_db, concat_repy,
                                         output_blast, threads=cpu_cores)

            current_results = fo.read_tabular(output_blast)
            # get raw score and sequence length
            new_self_scores = {l[0]: ((int(l[3])*3)+3, float(l[-1]))
                               for l in current_results
                               if l[0] == l[4]}
        
            # need to be careful not to update this if user does not want to add inferred alleles...
            self_scores = {**self_scores, **new_self_scores}

            # some representatives might match against common unclassified sequences
            # those are paralogous

    # return paths to classification files
    # mapping between genome identifiers and integer identifiers
    # path to Fasta file with distinct DNA sequences to get inferred alleles
    return [classification_files, inv_map, unique_fasta, dna_distinct_htable, new_reps, self_scores]


# add output with unclassified CDSs!
# add output with sequences for missing data classes!
def main(input_files, schema_directory, output_directory, ptf_path,
         blast_score_ratio, minimum_length, translation_table,
         size_threshold, word_size, window_size, clustering_sim,
         cpu_cores, blast_path, cds_input, prodigal_mode, only_exact,
         add_inferred, no_cleanup):

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

    results = allele_calling(input_files, schema_directory, output_directory,
                             ptf_path, blast_score_ratio, minimum_length,
                             translation_table, size_threshold, word_size,
                             window_size, clustering_sim, cpu_cores, blast_path,
                             prodigal_mode, cds_input, only_exact)

    # sort classification files to have allele call matrix format similar to v2.0
    results[0] = {k: results[0][k] for k in sorted(list(results[0].keys()))}

    # count total for each classification type
    global_counts, total_cds = count_classifications(results[0])

    # results in results_alleles.tsv and total CDSs that were classified do not match...
    print('Classified a total of {0} CDSs.'.format(total_cds))
    print('EXC: {EXC}\n'
          'INF: {INF}\n'
          'NIPHEM: {NIPHEM}\n'
          'NIPH: {NIPH}\n'
          'ASM: {ASM}\n'
          'ALM: {ALM}\n'
          'PLOT3: {PLOT3}\n'
          'PLOT5: {PLOT5}\n'
          'LOTSC: {LOTSC}\n'.format(**global_counts))

########## Test id assignment! Exact protein matches correctly added as INF?

    if only_exact is False:

        new_alleles = assign_ids(results[0], schema_directory)
    
        # get seqids that match hashes
        for k, v in new_alleles.items():
            for r in v:
                r.append(results[3][r[0]][0])
    
        # get info for new representative alleles that must be added to files in the short directory
        reps_info = {}
        for k, v in new_alleles.items():
            locus_id = fo.get_locus_id(k)
            current_results = results[4].get(locus_id, None)
            if current_results is not None:
                for e in current_results:
                    reps_info.setdefault(locus_id, []).append(list(e)+[l[1] for l in v if l[0] == e[1]])
    
        # need to be careful not to update this if user does not want to add inferred alleles...
        # update self_scores
        for k, v in reps_info.items():
            for r in v:
                new_id = k+'_'+r[-1]
                results[-1][new_id] = results[-1][r[0]]
            
        # delete old entries
        for k, v in reps_info.items():
            for r in v:
                try:
                    del(results[-1][r[0]])
                except:
                    continue
        # need to be careful not to update this if user does not want to add inferred alleles...
        # save updated self-scores
        self_score_file = fo.join_paths(schema_directory, ['short', 'self_scores'])
        fo.pickle_dumper(results[-1], self_score_file)
    
        if add_inferred is True:
            if len(new_alleles) > 0:
                # add inferred alleles to schema
                added = add_inferred_alleles(new_alleles, reps_info, results[2])
                print('Added {0} novel alleles to schema.'.format(added[0]))
                print('Added {0} representative alleles to schema.'.format(added[1]))
            else:
                print('No new alleles to add to schema.')

    end_time = pdt.get_datetime()

    # create output files
    results_dir = write_outputs(results[0], results[1], output_directory,
                                start_time, end_time, cpu_cores, blast_score_ratio)

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
