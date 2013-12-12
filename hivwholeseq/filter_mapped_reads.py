#!/usr/bin/env python
# vim: fdm=marker
'''
author:     Fabio Zanini
date:       26/08/13
content:    Build a subset of the mapped reads excluding mismappings.
'''
# Modules
import os
import argparse
from operator import itemgetter
import pysam
import numpy as np
from Bio import SeqIO


# Horizontal import of modules from this folder
from hivwholeseq.datasets import MiSeq_runs
from hivwholeseq.adapter_info import load_adapter_table
from hivwholeseq.filenames import get_consensus_filename, get_mapped_filename, \
        get_filter_mapped_summary_filename, get_mapped_suspicious_filename
from hivwholeseq.mapping_utils import get_ind_good_cigars, convert_sam_to_bam,\
        pair_generator, get_range_good_cigars
from hivwholeseq.fork_cluster import fork_filter_mapped as fork_self
from hivwholeseq.samples import samples



# Globals
maxreads = 1e10
match_len_min = 30
trim_bad_cigars = 3



# Functions
def plot_distance_histogram(data_folder, adaID, fragment, counts, savefig=False):
    '''Plot the histogram of distance from consensus'''
    from hivwholeseq.filenames import get_distance_from_consensus_figure_filename as gff
    import matplotlib.pyplot as plt

    # Linear histogram
    fig, ax = plt.subplots(1, 1)
    ax.set_xlabel('Hamming distance')
    ax.set_ylabel('# read pairs')
    ax.set_title('adaID '+adaID+', '+fragment)
    ax.set_xlim(-0.5, 0.5 + counts.nonzero()[0][-1])

    ax.plot(np.arange(len(counts)), counts, 'b', lw=2)
    if savefig:
        outputfile = gff(data_folder, adaID, fragment)
        fig.savefig(outputfile)
        plt.close(fig)

    # Log cumulative histogram
    fig, ax = plt.subplots(1, 1)
    ax.set_xlabel('Hamming distance')
    ax.set_ylabel('# read pairs < x')
    ax.set_title('adaID '+adaID+', '+fragment)
    ax.set_xlim(-0.5, 0.5 + counts.nonzero()[0][-1])
    ax.set_ylim(1.0 / counts.sum() * 0.9, 1.1)
    ax.set_yscale('log')

    y = 1.0 - 1.0 * np.cumsum(counts) / counts.sum()
    ax.plot(np.arange(len(counts)), y, 'b', lw=2)
    if savefig:
        outputfile = gff(data_folder, adaID, fragment, cumulative=True, yscale='log')
        fig.savefig(outputfile)
        plt.close(fig)


def plot_distance_histogram_sliding_window(data_folder, adaID, fragment,
                                           lref,
                                           counts, binsize=200,
                                           savefig=False):
    '''Plot the distance histogram along the genome'''
    from hivwholeseq.filenames import get_distance_from_consensus_figure_filename as gff
    import matplotlib.pyplot as plt
    from matplotlib import cm

    # Figure max x
    xmax = counts.nonzero()[1].max()

    # Linear histogram
    fig, ax = plt.subplots(1, 1)
    ax.set_xlabel('Hamming distance')
    ax.set_ylabel('# read pairs')
    ax.set_title('adaID '+adaID+', '+fragment)
    ax.set_xlim(-0.5, 0.5 + xmax)

    for i, count in enumerate(counts):
        color = cm.jet(int(255.0 * i / counts.shape[0]))
        start = binsize * i
        end = min(binsize * (i+1), lref)
        ax.plot(np.arange(counts.shape[1]), count, lw=2,
                color=color, label=str(start)+' to '+str(end))
    ax.legend(loc=1)

    if savefig:
        outputfile = gff(data_folder, adaID, fragment, sliding_window=True)
        fig.savefig(outputfile)
        plt.close(fig)


    # Log cumulative histogram
    fig, ax = plt.subplots(1, 1)
    ax.set_xlabel('Hamming distance')
    ax.set_ylabel('# read pairs')
    ax.set_title('adaID '+adaID+', '+fragment)
    ax.set_xlim(-0.5, 0.5 + xmax)
    ax.set_ylim(1.0 / counts.sum(axis=1).max() * 0.9, 1.1)
    ax.set_yscale('log')

    for i, count in enumerate(counts):
        color = cm.jet(int(255.0 * i / counts.shape[0]))
        start = binsize * i
        end = min(binsize * (i+1), lref)
        y = 1.0 - 1.0 * np.cumsum(count) / count.sum()
        ax.plot(np.arange(counts.shape[1]), y, lw=2,
                color=color, label=str(start)+' to '+str(end))
    ax.legend(loc=1)

    if savefig:
        outputfile = gff(data_folder, adaID, fragment, cumulative=True,
                         sliding_window=True)
        fig.savefig(outputfile)
        plt.close(fig)


def get_distance_from_consensus(ref, reads, VERBOSE=0):
    '''Get the number of mismatches (ins = 1, del = 1) from consensus'''
    ds = []
    for read in reads:
        d = 0
        pos_ref = read.pos
        pos_read = 0
        for (bt, bl) in read.cigar:
            if bt == 1:
                d += 1
                pos_read += bl
            elif bt == 2:
                d += 1
                pos_ref += bl
            elif bt == 0:
                seqb = np.fromstring(read.seq[pos_read: pos_read + bl], 'S1')
                d += (seqb != ref[pos_ref: pos_ref + bl]).sum()
                pos_ref += bl
                pos_read += bl
        ds.append(d)
    return np.array(ds, int)


def check_overhanging_reads(reads, refl):
    '''Check for reads overhanging beyond the fragment edges'''
    skip = False
    for read in reads:
        # Check overhangs
        read_start = read.pos
        read_end = read.pos + sum(x[1] for x in read.cigar if x[0] != 1)
        if (((read_start == 0) and (read.cigar[0][0] == 1)) or
            ((read_end == refl) and (read.cigar[-1][0] == 1))):
            skip = True
            break
    return skip


def trim_bad_cigar(reads, match_len_min=match_len_min,
                   trim_left=trim_bad_cigars, trim_right=trim_bad_cigars):
    '''Trim away bad CIGARs from the sides'''

    for read in reads:
        # Get good CIGARs
        (good_cigars, first_good_cigar, last_good_cigar) = \
                get_ind_good_cigars(read.cigar, match_len_min=match_len_min,
                                    full_output=True)

        # If no good CIGARs, give up
        if not good_cigars.any():
            return True
        
        # FIXME: trim also good reads of a few bases, just for testing
        # FIXME: we do not need this, but leave the code there for now
        elif good_cigars.all():
            continue
            #trim_good = 0
            #cigar = list(read.cigar)
            #cigar[0] = (cigar[0][0], cigar[0][1] - trim_good)
            #cigar[-1] = (cigar[-1][0], cigar[-1][1] - trim_good)
            #start_read = trim_good
            #end_read = start_read + sum(bl for (bt, bl) in cigar if bt in (0, 1))
            #start_ref = read.pos + start_read

        else:

            # Get the good CIGARs coordinates
            ((start_read, end_read),
             (start_ref, end_ref)) = \
                    get_range_good_cigars(read.cigar, read.pos,
                                          match_len_min=match_len_min,
                                          trim_left=trim_left,
                                          trim_right=trim_right)

            # Trim CIGAR because of bad CIGARs at the edges
            cigar = read.cigar[first_good_cigar: last_good_cigar + 1]
            # Trim cigar block lengths
            if first_good_cigar != 0:
                cigar[0] = (cigar[0][0],
                            cigar[0][1] - trim_left)
            if last_good_cigar != len(read.cigar) - 1:
                cigar[-1] = (cigar[-1][0],
                             cigar[-1][1] - trim_right)

            # Reset attributes
            seq = read.seq
            qual = read.qual
            read.seq = seq[start_read: end_read]
            read.qual = qual[start_read: end_read]
            read.pos = start_ref
            read.cigar = cigar    

    # Mate pair stuff and insert size
    reads[0].mpos = reads[1].pos
    reads[1].mpos = reads[0].pos

    # Insert size
    i_fwd = reads[0].is_reverse
    i_rev = not i_fwd
    isize = reads[i_rev].pos + sum(bl for (bt, bl) in reads[i_rev].cigar
                                   if bt in (0, 2)) - reads[i_fwd].pos
    
    # Trash pair if the insert size is negative (complete cross-overhang)
    #               ----->
    #   <------
    if isize <= 0:
        return True

    reads[i_fwd].isize = isize
    reads[i_rev].isize = -isize

    return False


def filter_reads(data_folder, adaID, fragment, VERBOSE=0,
                 n_cycles=600,
                 max_mismatches=30,
                 susp_mismatches=20,
                 summary=True):
    '''Filter the reads to good chunks'''
    frag_gen = fragment[:2]

    reffilename = get_consensus_filename(data_folder, adaID, frag_gen)
    refseq = SeqIO.read(reffilename, 'fasta')
    ref = np.array(refseq)

    bamfilename = get_mapped_filename(data_folder, adaID, frag_gen, type='bam',
                                      filtered=False)
    if not os.path.isfile(bamfilename):
        convert_sam_to_bam(bamfilename)

    outfilename = get_mapped_filename(data_folder, adaID, frag_gen, type='bam',
                                     filtered=True)
    suspiciousfilename = get_mapped_suspicious_filename(data_folder, adaID, frag_gen)
    trashfilename = outfilename[:-4]+'_trashed.bam'
 
    with pysam.Samfile(bamfilename, 'rb') as bamfile:
        with pysam.Samfile(outfilename, 'wb', template=bamfile) as outfile,\
             pysam.Samfile(suspiciousfilename, 'wb', template=bamfile) as suspfile,\
             pysam.Samfile(trashfilename, 'wb', template=bamfile) as trashfile:
 
            # Iterate over all pairs
            n_good = 0
            n_wrongname = 0
            n_unmapped = 0
            n_unpaired = 0
            n_mutator = 0
            n_suspect = 0
            n_mismapped_edge = 0
            n_badcigar = 0
            histogram_distance_from_consensus = np.zeros(n_cycles + 1, int)
            binsize = 200
            histogram_dist_along = np.zeros((len(ref) // binsize + 1,
                                             n_cycles + 1), int)
            for irp, reads in enumerate(pair_generator(bamfile)):

                # Limit to the first reads
                if 2 * irp >= maxreads: break
            
                # Assign names
                (read1, read2) = reads
                i_fwd = reads[0].is_reverse

                # Check a few things to make sure we are looking at paired reads
                if read1.qname != read2.qname:
                    n_wrongname += 1
                    raise ValueError('Read pair '+str(irp)+': reads have different names!')

                # Ignore unmapped reads
                if read1.is_unmapped or read2.is_unmapped:
                    if VERBOSE >= 2:
                        print 'Read pair '+read1.qname+': unmapped'
                    n_unmapped += 1
                    map(trashfile.write, reads)
                    continue
            
                # Ignore not properly paired reads (this includes mates sitting on
                # different fragments)
                if (not read1.is_proper_pair) or (not read2.is_proper_pair):
                    if VERBOSE >= 2:
                        print 'Read pair '+read1.qname+': not properly paired'
                    n_unpaired += 1
                    map(trashfile.write, reads)
                    continue

                # Mismappings are sometimes at fragment edges:
                # Check for overhangs beyond the edge
                skip = check_overhanging_reads(reads, len(ref))
                if skip:
                    n_mismapped_edge += 1
                    map(trashfile.write, reads)
                    continue
                    
                # Mismappings are often characterized by many mutations:
                # check the number of mismatches and skip reads with too many
                dc = get_distance_from_consensus(ref, reads, VERBOSE=VERBOSE)
                histogram_distance_from_consensus[dc.sum()] += 1
                hbin = (reads[i_fwd].pos + reads[i_fwd].isize / 2) // binsize
                histogram_dist_along[hbin, dc.sum()] += 1
                if (dc.sum() > max_mismatches):
                    if VERBOSE >= 2:
                        print 'Read pair '+read1.qname+': too many mismatches '+\
                                '('+str(dc[0])+' + '+str(dc[1])+')'
                    n_mutator += 1
                    map(trashfile.write, reads)
                    continue

                # Check for contamination from other PCR plates. Typically,
                # contamination happens for only one fragment, whereas superinfection
                # happens for all. At this stage, we can only give clues about
                # cross-contamination, the rest will be done in a script downstream
                # (here we could TAG suspicious reads for contamination)
                elif (dc.sum() > susp_mismatches):
                    n_suspect += 1
                    map(suspfile.write, reads)
                    continue

                # Trim the bad CIGARs from the sides, if there are any good ones
                skip = trim_bad_cigar(reads, match_len_min=match_len_min,
                                       trim_left=trim_bad_cigars,
                                       trim_right=trim_bad_cigars)
                if skip:
                    n_badcigar += 1
                    map(trashfile.write, reads)
                    continue

                # TODO: we might want to incorporate some more stringent
                # criterion here, to avoid short reads, cross-overhang, etc.

                # Write the output
                n_good += 1
                map(outfile.write, reads)

    if VERBOSE >= 1:
        print 'Read pairs: '
        print 'Good:', n_good
        print 'Unmapped:', n_unmapped
        print 'Unpaired:', n_unpaired
        print 'Mispapped at edge:', n_mismapped_edge
        print 'Many-mutations:', n_mutator
        print 'Suspect contaminations:', n_suspect
        print 'Bad CIGARs:', n_badcigar

    if summary:
        summary_filename = get_filter_mapped_summary_filename(data_folder, adaID, fragment)
        with open(summary_filename, 'a') as f:
            f.write('Filter results: adaID '+adaID+fragment+'\n')
            f.write('Total:\t\t\t'+str(irp + 1)+'\n')
            f.write('Good:\t\t\t'+str(n_good)+'\n')
            f.write('Unmapped:\t\t'+str(n_unmapped)+'\n')
            f.write('Unpaired:\t\t'+str(n_unpaired)+'\n')
            f.write('Mismapped at edge:\t'+str(n_mismapped_edge)+'\n')
            f.write('Many-mutations:\t\t'+str(n_mutator)+'\n')
            f.write('Suspect contaminations:\t'+str(n_suspect)+'\n')
            f.write('Bad CIGARs:\t\t'+str(n_badcigar)+'\n')

        plot_distance_histogram(data_folder, adaID, frag_gen,
                                histogram_distance_from_consensus,
                                savefig=True)

        plot_distance_histogram_sliding_window(data_folder, adaID, frag_gen,
                                               len(ref),
                                               histogram_dist_along,
                                               binsize=binsize,
                                               savefig=True)



# Script
if __name__ == '__main__':

    # Input arguments
    parser = argparse.ArgumentParser(description='Filter mapped reads')
    parser.add_argument('--run', required=True,
                        help='Seq run to analyze (e.g. 28, 37)')
    parser.add_argument('--adaIDs', nargs='*',
                        help='Adapter IDs to analyze (e.g. 2 16)')
    parser.add_argument('--fragments', nargs='*',
                        help='Fragment to map (e.g. F1 F6)')
    parser.add_argument('--verbose', type=int, default=0,
                        help=('Verbosity level [0-3]'))
    parser.add_argument('--submit', action='store_true', default=False,
                        help='Submit the job to the cluster')
    parser.add_argument('--no-summary', action='store_false', dest='summary',
                        help='Do not save results in a summary file')
    parser.add_argument('--max-mismatches', type=int, default=30,
                        dest='max_mismatches',
                        help='Maximal number of mismatches from consensus')
    parser.add_argument('--suspicious-mismatches', type=int, default=20,
                        dest='susp_mismatches',
                        help='Threshold number of mismatches from consensus \
                              for suspicion of contamination')

    args = parser.parse_args()
    seq_run = args.run
    adaIDs = args.adaIDs
    fragments = args.fragments
    VERBOSE = args.verbose
    submit = args.submit
    summary=args.summary
    max_mismatches = args.max_mismatches
    susp_mismatches = args.susp_mismatches

    # Specify the dataset
    dataset = MiSeq_runs[seq_run]
    data_folder = dataset['folder']

    # If the script is called with no adaID, iterate over all
    if not adaIDs:
        adaIDs = dataset['adapters']
    if VERBOSE >= 3:
        print 'adaIDs', adaIDs

    # Iterate over all requested samples
    for adaID in adaIDs:

        # If the script is called with no fragment, iterate over all
        samplename = dataset['samples'][dataset['adapters'].index(adaID)]
        if not fragments:
            fragments_sample = samples[samplename]['fragments']
        else:
            from re import findall
            fragments_all = samples[samplename]['fragments']
            fragments_sample = []
            for fragment in fragments:
                frs = filter(lambda x: fragment in x, fragments_all)
                if len(frs):
                    fragments_sample.append(frs[0])
        if VERBOSE >= 3:
            print 'adaID '+adaID+': fragments '+' '.join(fragments_sample)

        for fragment in fragments_sample:

            # Submit to the cluster self if requested
            if submit:
                fork_self(seq_run, adaID, fragment, VERBOSE=VERBOSE, summary=summary)
                continue

            if summary:
                sfn = get_filter_mapped_summary_filename(data_folder, adaID, fragment)
                with open(sfn, 'w') as f:
                    f.write('Call: python filter_mapped_reads.py'+\
                            ' --run '+seq_run+\
                            ' --adaIDs '+adaID+\
                            ' --fragments '+fragment+\
                            ' --max-mismatches '+str(max_mismatches)+\
                            ' --verbose '+str(VERBOSE))
                    f.write('\n')

            # Other adaIDs
            adaIDs_other = list(adaIDs)
            del adaIDs_other[adaIDs_other.index(adaID)]

            # Filter reads
            filter_reads(data_folder, adaID, fragment, VERBOSE=VERBOSE,
                         n_cycles=dataset['n_cycles'],
                         max_mismatches=max_mismatches,
                         susp_mismatches=susp_mismatches,
                         summary=summary)
