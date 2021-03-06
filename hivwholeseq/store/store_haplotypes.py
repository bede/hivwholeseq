#!/usr/bin/env python
# vim: fdm=marker
'''
author:     Fabio Zanini
date:       11/12/14
content:    Store local haplotypes.
'''
# Modules
import os
import sys
import argparse
from operator import itemgetter, attrgetter
import numpy as np
from matplotlib import cm
import matplotlib.pyplot as plt
from Bio import Phylo

from hivwholeseq.utils.generic import mkdirs
from hivwholeseq.utils.mapping import align_muscle
from hivwholeseq.utils.argparse import PatientsAction
from hivwholeseq.patients.patients import load_patients, iterpatient



# Functions



# Script
if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Store local haplotypes',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)    
    parser.add_argument('--patients', action=PatientsAction,
                        help='Patients to analyze')
    parser.add_argument('--regions', nargs='+', required=True,
                        help='Genomic regions (e.g. V3 IN)')
    parser.add_argument('--verbose', type=int, default=2,
                        help='Verbosity level [0-4]')
    parser.add_argument('--maxreads', type=int, default=-1,
                        help='Number of reads analyzed per sample')
    parser.add_argument('--freqmin', type=int, default=0.01,
                        help='Minimal frequency to keep the haplotype')
    parser.add_argument('--countmin', type=int, default=3,
                        help='Minimal observations to keep the haplotype')
    parser.add_argument('--save', action='store_true',
                        help='Save alignment to file')

    args = parser.parse_args()
    pnames = args.patients
    regions = args.regions
    VERBOSE = args.verbose
    maxreads = args.maxreads
    freqmin = args.freqmin
    countmin = args.countmin
    use_save = args.save

    patients = load_patients()
    if pnames is not None:
        patients = patients.loc[pnames]

    for pname, patient in iterpatient(patients):
        for region in regions:
            if VERBOSE >= 1:
                print pname, region
    
            if VERBOSE >= 2:
                print 'Get region haplotypes'
            datum = patient.get_local_haplotype_count_trajectories(\
                           region,
                           filters=['noN',
                                    'mincount='+str(countmin),
                                    'freqmin='+str(freqmin),
                                   ],
                           VERBOSE=VERBOSE,
                           align=True,
                           return_dict=True)
            datum['times'] = patient.times[datum['ind']]

            if use_save:
                if VERBOSE >= 2:
                    print 'Save to file'

                if not datum['ind']:
                    print 'No haplotypes'
                    continue

                fn_out = patient.get_haplotype_count_trajectory_filename(region)
                mkdirs(os.path.dirname(fn_out))
                np.savez_compressed(fn_out,
                                    hct=datum['hct'],
                                    ind=datum['ind'],
                                    times=datum['times'],
                                    seqs=datum['seqs'],
                                    ali=datum['alim'],
                                   )
