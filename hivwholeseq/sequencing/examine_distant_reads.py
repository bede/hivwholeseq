# vim: fdm=marker
'''
author:     Fabio Zanini
date:       13/09/14
content:    Examine reads that are more than the threshold from consensus
            (typically 30 changes) to find out what they are.
'''
# Modules
import os
import argparse
import numpy as np
import pysam

from hivwholeseq.sequencing.filenames import get_filter_mapped_summary_filename, \
        get_mapped_filename
from hivwholeseq.sequencing.samples import SampleSeq, load_samples_sequenced


# Functions
def fish_distant_reads(bamfilename, ref, max_mismatches=30, VERBOSE=0):
    '''Fish distant reads from the trash'''
    import numpy as np

    from hivwholeseq.mapping_utils import pair_generator, reads_to_seqrecord
    from hivwholeseq.sequencing.filter_mapped_reads import check_overhanging_reads, \
            get_distance_from_consensus

    distances = []
    seqs = []
    with pysam.Samfile(bamfilename, 'rb') as bamfile:
        for irp, reads in enumerate(pair_generator(bamfile)):
            if VERBOSE >= 2:
                if not ((irp + 1) % 10000):
                    print irp + 1

            (read1, read2) = reads
            i_fwd = reads[0].is_reverse

            # Check a few things to make sure we are looking at paired reads
            if read1.qname != read2.qname:
                raise ValueError('Read pair '+str(irp)+': reads have different names!')

            # Ignore unmapped reads
            if read1.is_unmapped or read2.is_unmapped:
                continue
            
            # Ignore not properly paired reads (this includes mates sitting on
            # different fragments)
            if (not read1.is_proper_pair) or (not read2.is_proper_pair):
                continue

            # Check for overhangs beyond the edge
            skip = check_overhanging_reads(reads, len(ref))
            if skip:
                continue

            # Fish our babies
            dc = get_distance_from_consensus(ref, reads, VERBOSE=VERBOSE)
            if (dc.sum() > max_mismatches):
                if VERBOSE >= 3:
                    print 'Gotcha!', reads[0].qname
                seqs.append(reads[0])
                seqs.append(reads[1])
                distances.append(dc)

        seqs = list(pair_generator(reads_to_seqrecord(seqs)))

    distances = np.array(distances, int)
    return (distances, seqs)



# Script
if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Examine distant reads',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)    
    parser.add_argument('--runs', nargs='+',
                        help='Seq runs to analyze (e.g. Tue28, test_tiny)')
    parser.add_argument('--adaIDs', nargs='+',
                        help='Adapter IDs to analyze (e.g. TS2)')
    parser.add_argument('--fragments', nargs='+',
                        help='Fragment to map (e.g. F1 F6)')
    parser.add_argument('--nopatients', action='store_false', dest='use_pats',
                        help='Include non-patient samples (e.g. reference strains)')
    parser.add_argument('--verbose', type=int, default=0,
                        help='Verbosity level [0-3]')

    args = parser.parse_args()
    seq_runs = args.runs
    adaIDs = args.adaIDs
    fragments = args.fragments
    use_pats = args.use_pats
    VERBOSE = args.verbose

    samples = load_samples_sequenced()
    if seq_runs is not None:
        samples = samples.loc[samples['seq run'].isin(seq_runs)]
    
    if adaIDs is not None:
        samples = samples.loc[samples.adapter.isin(adaIDs)]
    
    if use_pats:
        samples = samples.loc[samples['patient sample'] != 'nan']

    if fragments is None:
        fragments = ['F'+str(i+1) for i in xrange(6)]

    for samplename, sample in samples.iterrows():
        sample = SampleSeq(sample)
        data_folder = sample.seqrun_folder
        adaID = sample.adapter

        for fragment in fragments:
            if VERBOSE >= 1:
                print sample['seq run'], adaID, fragment, samplename,

            # Read the summary filename of the filter_mapped, and find out whether
            # there are many distant reads (a few are normal)
            fn = get_filter_mapped_summary_filename(data_folder, adaID, fragment)
            found = False
            with open(fn, 'r') as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line[:4] == 'Good':
                        n_good = int(line.split()[-1])

                    elif line[:14] == 'Many-mutations':
                        n_distant = int(line.split()[-1])
                        found = True
                        break

            if not found:
                if VERBOSE >= 1:
                    print 'not filtered (probably no HIV reads)'
                continue

            frac_dist = 1.0 * n_distant / n_good
            if frac_dist < 0.01:
                if VERBOSE >= 1:
                    print 'OK'
                continue
            
            if VERBOSE >= 1:
                print '{:3.0%}'.format(frac_dist), 'of reads are distant'

            # Distant reads end up in the trash (oh, no!)
            consrec = sample.get_consensus(fragment)
            bamfilename = get_mapped_filename(data_folder, adaID, fragment,
                                              filtered=True, trashed=True)

            (distances, seqs) = fish_distant_reads(bamfilename, consrec, VERBOSE=VERBOSE)
            

            #TODO
