#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Purpose
-------

This module contains functions related with the execution
of the BLAST software.

Code documentation
------------------
"""


import subprocess

try:
    from utils import iterables_manipulation as im
except:
    from CHEWBBACA.utils import iterables_manipulation as im


def make_blast_db(makeblastdb_path, input_fasta, output_path, db_type,
                  ignore=None):
    """ Creates a BLAST database.

    Parameters
    ----------
    makeblastdb_path : str
        Path to the 'maskeblastdb' executable.
    input_fasta : str
        Path to the FASTA file that contains the sequences
        that should be added to the BLAST database.
    output_path : str
        Path to the directory where the database files
        will be created. Database files will have the same
        basename as the `makeblastdb_path`.
    db_type : str
        Type of the database, nucleotide (nuc) or
        protein (prot).
    ignore : list or NoneType
        List with BLAST warnings that should be ignored.

    Returns
    -------
    stderr : list
        A list with the warnings and errors raised by BLAST.
    """

    blastdb_cmd = [makeblastdb_path, '-in', input_fasta,
                   '-out', output_path, '-parse_seqids',
                   '-dbtype', db_type]

    makedb_cmd = subprocess.Popen(blastdb_cmd,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)

    stderr = makedb_cmd.stderr.readlines()

    if len(stderr) > 0:
        stderr = im.decode_str(stderr, 'utf8')
        if ignore is not None:
            stderr = im.filter_list(stderr, ignore)

    return stderr


def determine_blast_task(sequences):
    """ Determine the type of task that should be used to
        run BLASTp (alignments with short sequences require
        definition of different task).

    Parameters
    ----------
    sequences : list
        List with protein sequences.

    Returns
    -------
    blast_task : str
        A string that indicates the type of BLASTp
        task to run ('blastp' if all sequences are
        bigger than 30 amino acids, 'blastp-short'
        otherwise).
    """

    blast_task = 'blastp'
    sequence_lengths = [len(p) for p in sequences]
    minimum_length = min(sequence_lengths)
    if minimum_length < 30:
        blast_task = 'blastp-short'

    return blast_task


def run_blast(blast_path, blast_db, fasta_file, blast_output,
              max_hsps=1, threads=1, ids_file=None, blast_task=None,
              max_targets=None, ignore=None):
    """ Execute BLAST to align sequences in a FASTA file
        against a BLAST database.

    Parameters
    ----------
    blast_path : str
        Path to BLAST executables.
    blast_db : str
        Path to the BLAST database.
    fasta_file : str
        Path to the FASTA file with sequences to
        align against the BLAST database.
    blast_output : str
        Path to the file that will be created to
        store BLAST results.
    max_hsps : int
        Maximum number of High Scoring Pairs per
        pair of aligned sequences.
    threads : int
        Number of threads/cores used to run BLAST.
    ids_file : str
        Path to a file with sequence identifiers,
        one per line. Sequences will only be aligned
        to the sequences in the BLAST database that
        have any of the identifiers in this file.
    blast_task : str
        Type of BLAST task.
    max_targets : int
        Maximum number of target/subject sequences
        to align against.
    ignore : list or None
        List with BLAST warnings that should be ignored.

    Returns
    -------
    stderr : list
        A list with the warnings and errors raised by BLAST.
    """

    blast_args = [blast_path, '-db', blast_db, '-query', fasta_file,
                  '-out', blast_output, '-outfmt', '6 qseqid qstart qend qlen sseqid slen score',
                  '-max_hsps', str(max_hsps), '-num_threads', str(threads),
                  '-evalue', '0.001']

    if ids_file is not None:
        blast_args.extend(['-seqidlist', ids_file])
    if blast_task is not None:
        blast_args.extend(['-task', blast_task])
    if max_targets is not None:
        blast_args.extend(['-max_target_seqs', str(max_targets)])

    blast_proc = subprocess.Popen(blast_args,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)

    stderr = blast_proc.stderr.readlines()

    if len(stderr) > 0:
        stderr = im.decode_str(stderr, 'utf8')
        if ignore is not None:
            stderr = im.filter_list(stderr, ignore)

    return stderr
