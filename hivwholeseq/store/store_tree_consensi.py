# vim: fdm=marker
'''
author:     Fabio Zanini
date:       13/01/15
content:    Get the tree of consensi from a patient.
'''
# Modules
import sys
import os
import argparse
from operator import attrgetter
import numpy as np
from Bio import SeqIO, AlignIO

from hivwholeseq.utils.generic import mkdirs
from hivwholeseq.sequencing.samples import SampleSeq
from hivwholeseq.patients.patients import load_patients, Patient, SamplePat
from hivwholeseq.utils.tree import build_tree_fasttree
from hivwholeseq.utils.nehercook.ancestral import ancestral_sequences
from hivwholeseq.utils.tree import tree_to_json
from hivwholeseq.utils.generic import write_json



# Globals
regionsprot = ['PR', 'RT']



# Functions
def annotate_tree(patient, tree, VERBOSE=0,
                  fields=('DSI', 'muts', 'VL', 'ntemplates', 'CD4',
                          'patient')):
    '''Annotate a tree with info on the nodes'''
    from hivwholeseq.utils.tree import add_mutations_tree

    for node in tree.get_terminals():
        label = node.name
        entries = label.split('_')
        node.name = entries[0]

        if node.name == 'reference':
            continue

        # Days Since Infection
        if 'DSI' in fields:
            time = float(entries[0])
            node.DSI = time
        
        sample = patient.samples.loc[patient.times == time].iloc[0]
    
        if 'CD4' in fields:
            node.CD4 = sample['CD4+ count']

        if 'VL' in fields:
            node.VL = sample['viral load']

        # FIXME: shall we check the patient method for this?
        # Well, we are going to quantify fragment-by-fragment, so...
        if 'ntemplates' in fields:
            node.ntemplates = sample['n templates']

    if 'subtype' in fields:
        for node in tree.get_terminals() + tree.get_nonterminals():
            node.subtype = patient.Subtype
    
    if 'patient' in fields:
        for node in tree.get_terminals() + tree.get_nonterminals():
            node.patient = patient.code

    if 'muts' in fields:
        add_mutations_tree(tree, translate=False, mutation_attrname='muts')

    if 'mutsprot' in fields:
        add_mutations_tree(tree, translate=True, mutation_attrname='mutsprot')



# Script
if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Align consensi',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)    
    parser.add_argument('--patients', nargs='+', default=['all'],
                        help='Patients to analyze')
    parser.add_argument('--regions', nargs='*',
                        help='Regions to analyze (e.g. V3 F6)')
    parser.add_argument('--verbose', type=int, default=0,
                        help='Verbosity level [0-4]')
    parser.add_argument('--save', action='store_true',
                        help='Save alignment to file')
    parser.add_argument('--plot', action='store_true',
                        help='Plot phylogenetic tree. Requires --save and --tree')

    args = parser.parse_args()
    pnames = args.patients
    regions = args.regions
    VERBOSE = args.verbose
    use_save = args.save
    use_plot = args.plot

    patients = load_patients()
    if pnames != ['all']:
        patients = patients.iloc[patients.index.isin(pnames)]

    for pname, patient in patients.iterrows():
        patient = Patient(patient)
        patient.discard_nonsequenced_samples()

        if regions is None:
            refseq_gw = patient.get_reference('genomewide', 'gb')
            regionspat = map(attrgetter('id'), refseq_gw.features) + ['genomewide']
        else:
            regionspat = regions

        for region in regionspat:
            if VERBOSE >= 1:
                print pname, region
                if VERBOSE == 1:
                    print ''


            if VERBOSE >= 2:
                print 'Get alignment'
            ali = patient.get_consensi_alignment(region)


            if VERBOSE >= 2:
                print 'Build tree'
                sys.stdout.flush()
            tree = build_tree_fasttree(ali, rootname=ali[0].id,
                                       VERBOSE=VERBOSE)


            if VERBOSE >= 2:
                print 'Infer ancestral sequences'
            a = ancestral_sequences(tree, ali, alphabet='ACGT-N', copy_tree=False,
                                    attrname='sequence', seqtype='str')
            a.calc_ancestral_sequences()
            a.cleanup_tree()


            if VERBOSE >= 2:
                print 'Annotate tree'
            fields = ['DSI', 'muts', 'VL', 'ntemplates', 'CD4', 'subtype']
            if region in regionsprot:
                fields.append('mutsprot')
            annotate_tree(patient, tree,
                          fields=fields,
                          VERBOSE=VERBOSE)


            if VERBOSE >= 2:
                print 'Ladderize tree'
            tree.ladderize()


            if use_save:
                if VERBOSE >= 2:
                    print 'Save tree (JSON)'
                fields.extend(['sequence', 'confidence'])
                fn = patient.get_consensi_tree_filename(region, format='json')
                tree_json = tree_to_json(tree.root, fields=fields)
                write_json(tree_json, fn)

            if use_plot:
                import matplotlib.pyplot as plt
                fig, ax = plt.subplots(figsize=(15, 12))
                Phylo.draw(tree, do_show=False, axes=ax)
                ax.set_title(pname+', '+region)

                x_max = max(tree.depths().itervalues())
                ax.set_xlim(0.995, 0.995 + (x_max - 0.995) * 1.4)
                ax.grid(True)
                
                plt.ion()
                plt.show()


