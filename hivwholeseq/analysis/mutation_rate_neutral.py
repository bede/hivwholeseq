# vim: fdm=marker
'''
author:     Fabio Zanini
date:       09/01/15
content:    Study divergence at conserved/non- synonymous sites in different
            patients.
'''
# Modules
import os
import argparse
from itertools import izip
from collections import defaultdict, Counter
import numpy as np
import pandas as pd
from matplotlib import cm
import matplotlib.pyplot as plt

from hivwholeseq.miseq import alpha, alphal
from hivwholeseq.patients.patients import load_patients, Patient
from hivwholeseq.utils.sequence import translate_with_gaps
from hivwholeseq.analysis.explore_codon_usage_patsubtype import get_degenerate_dict
import hivwholeseq.utils.plot
from hivwholeseq.analysis.explore_entropy_patsubtype import (
    get_subtype_reference_alignment, get_ali_entropy)
from hivwholeseq.cross_sectional.get_subtype_entropy import (
    get_subtype_reference_alignment_entropy)
from hivwholeseq.patients.one_site_statistics import get_codons_n_polymorphic


# Globals



# Functions
def print_info(data, indices, title=None):
    '''Print basic info'''
    num_all = (data
               .groupby(indices)['af']
               .count())
    num_all.name = '# alleles'
    num_poly = (data
                .loc[np.array(data['af']) > 0]
                .groupby(indices)['af']
                .count())
    num_poly.name = '# polymorphisms'
    frac = (num_poly / num_all).apply('{:1.1%}'.format)
    frac.name = 'percentage'

    if title is not None:
        print title
    print pd.concat([num_poly, num_all, frac], axis=1)


def get_mutation_rates(data, type='syn'):
    '''Get the mutation rate as fits of the increase in frequency'''
    indices = ['Class', 'Substitution']
    meangrouped = data.groupby(indices + ['Time']).mean()['af']
    pdata = meangrouped.unstack('Time')
    mu = (data.groupby([indices[-1]])['af'].mean())
    mu[:] = 0
    mu.name = 'synonymous mutation rate'

    for icl, (keys, arr) in enumerate(pdata.iterrows()):
        # Do it better
        if 'syn' not in keys:
            continue

        x = arr.index
        y = np.array(arr)

        # Linear LS fit (shall we do it on all data instead?)
        m = np.inner(x, y) / np.inner(x, x)

        mu.loc[keys[-1]] = m

    return mu


def comparison_Abram2010(mu):
    '''Print a comparison with Abram 2010, J. Virol.'''

    muAbram = mu.copy()
    muAbram.name = 'mutation rate Abram 2010'
    muAbram[:] = 0

    # Forward strand
    muAbram['C->A'] += 14
    muAbram['G->A'] += 146
    muAbram['T->A'] += 20
    muAbram['A->C'] += 1
    muAbram['G->C'] += 2
    muAbram['T->C'] += 18
    muAbram['A->G'] += 29
    muAbram['C->G'] += 0
    muAbram['T->G'] += 6
    muAbram['A->T'] += 3
    muAbram['C->T'] += 81
    muAbram['G->T'] += 4

    # Reverse strand
    muAbram['C->A'] += 24
    muAbram['G->A'] += 113
    muAbram['T->A'] += 32
    muAbram['A->C'] += 1
    muAbram['G->C'] += 2
    muAbram['T->C'] += 25
    muAbram['A->G'] += 13
    muAbram['C->G'] += 1
    muAbram['T->G'] += 8
    muAbram['A->T'] += 0
    muAbram['C->T'] += 61
    muAbram['G->T'] += 0

    muRescaled = (mu / mu.sum() * muAbram.sum()).astype(int)
    muRescaled.name = mu.name+' (rescaled)'

    print title
    print pd.concat([muAbram, muRescaled], axis=1)


def plot_mu_matrix(mu, time_unit='generation'):
    '''Plot the mutation rate matrix'''
    muM = np.ma.masked_all((4, 4))
    for ia1, a1 in enumerate(alpha[:4]):
        for ia2, a2 in enumerate(alpha[:4]):
            if a1+'->'+a2 in mu.index:
                muM[ia1, ia2] = mu.loc[a1+'->'+a2]

    if time_unit == 'generation':
        # Assume a generation time of 2 days
        muM *= 2

    fig, ax = plt.subplots()
    h = ax.imshow(np.log10(muM.T + 1e-10),
                  interpolation='nearest',
                  vmin=-9, vmax=-4)

    ax.set_xticks(np.arange(4))
    ax.set_yticks(np.arange(4))
    ax.set_xticklabels(alpha[:4])
    ax.set_yticklabels(alpha[:4])

    ax.set_xlabel('From:')
    ax.set_ylabel('To:')

    cb = fig.colorbar(h)
    cb.set_ticks(np.arange(-9, -3))
    cb.set_ticklabels(['$10^{'+str(x)+'}$' for x in xrange(-9, -3)])
    cb.set_label('changes / '+time_unit, rotation=270, labelpad=30)

    plt.tight_layout(rect=(-0.1, 0, 1, 1))

    plt.ion()
    plt.show()

plot_mu_matrix(mu)



# Script
if __name__ == '__main__':

    # Parse input args
    parser = argparse.ArgumentParser(
        description='Get mutation rate from the accumulation of synonymous minor alleles',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)    
    parser.add_argument('--patients', nargs='+',
                        help='Patient to analyze')
    parser.add_argument('--regions', nargs='+', required=True,
                        help='Regions to analyze (e.g. F1 p17)')
    parser.add_argument('--verbose', type=int, default=0,
                        help='Verbosity level [0-4]')
    parser.add_argument('--plot', nargs='?', default=None, const='2D',
                        help='Plot results')

    args = parser.parse_args()
    pnames = args.patients
    regions = args.regions
    VERBOSE = args.verbose
    plot = args.plot

    data = defaultdict(list)

    patients = load_patients()
    if pnames is not None:
        patients = patients.loc[pnames]

    for region in regions:
        if VERBOSE >= 1:
            print region

        try:
            Ssub = get_subtype_reference_alignment_entropy(region)
        except IOError:
            # FIXME: this is a hack
            Ssub = defaultdict(int)

        for ipat, (pname, patient) in enumerate(patients.iterrows()):

            patient = Patient(patient)
            aft, ind = patient.get_allele_frequency_trajectories(region,
                                                                 cov_min=1000,
                                                                 depth_min=300,
                                                                 VERBOSE=VERBOSE)
            if len(ind) == 0:
                continue

            # Get the coordinate map to HXB2 (and ref alignment)
            coomap = patient.get_map_coordinates_reference(region)
            coomap[:, 0] -= coomap[coomap[:, 1] == 0, 0][0]

            # NOTE: Pavel has sometimes cut the second half of the alignment (e.g. RT)
            if len(Ssub) < (coomap[:, 0]).max() + 1:
                coomap = coomap[coomap[:, 0] < len(Ssub)]
                aft = aft[:, :, :coomap[:, 1].max() + 1]

            coomap = dict(coomap[:, ::-1])

            times = patient.times[ind]

            icons = patient.get_initial_consensus_noinsertions(aft, VERBOSE=VERBOSE)
            cons = alpha[icons]
            
            if ('N' in cons) or ('-' in cons):
                continue

            prot = translate_with_gaps(cons)

            # Trim the stop codon if still there (why? why?)
            if prot[-1] == '*':
                icons = icons[:-3]
                cons = cons[:-3]
                prot = prot[:-1]
                aft = aft[:, :, :-3]

            # Premature stops in the initial consensus???
            if '*' in prot:
                continue

            ind_poly, pos_poly = get_codons_n_polymorphic(aft, icons, n=[0, 1], VERBOSE=VERBOSE)

            # FIXME: deal better with depth (this should be already there?)
            aft[aft < 2e-3] = 0

            for pos, pospoly in izip(ind_poly, pos_poly):

                # Forget the polymorphic positions, try all 3
                for pospoly  in xrange(3):
                
                    posdna = pos * 3 + pospoly
                    aftpos = aft[:, :, posdna].T


                    # Only keep positions that are also in HXB2 (so we get the subtype entropy)
                    if posdna not in coomap:
                        continue
                    Ssubpos = Ssub[coomap[posdna]]

                    # Get only non-masked time points
                    indpost = -aftpos[0].mask
                    if indpost.sum() == 0:
                        continue
                    timespos = times[indpost]
                    aftpos = aftpos[:, indpost]

                    anc = cons[posdna]
                    ianc = icons[posdna]

                    # Skip if the site is already polymorphic at the start
                    if aftpos[ianc, 0] < 0.95:
                        continue

                    for inuc, af in enumerate(aftpos[:4]):
                        nuc = alpha[inuc]
                        if nuc == anc:
                            continue

                        anccod = cons[pos * 3: (pos + 1) * 3]
                        mutcod = anccod.copy()
                        mutcod[pospoly] = nuc

                        anccod = ''.join(anccod)
                        mutcod = ''.join(mutcod)

                        ancaa = translate_with_gaps(anccod)
                        mutaa = translate_with_gaps(mutcod)

                        # Define the type of mutations (syn, nonsyn)
                        if ancaa == mutaa:
                            mutclass = 'syn'
                        else:
                            mutclass = 'nonsyn'

                        # Define transition/transversion
                        if frozenset(nuc+anc) in (frozenset('CT'), frozenset('AG')):
                            trclass = 'ts'
                        else:
                            trclass = 'tv'

                        mut = anc+'->'+nuc

                        # Get the whole trajectory for plots against time
                        data['aft'].extend([(region, pname, time,
                                             anccod, mutcod,
                                             anc, nuc, mut,
                                             Ssubpos,
                                             mutclass, trclass, af)
                                            for af, time in izip(aftpos[inuc], timespos)])

    data['aft'] = pd.DataFrame(data=data['aft'],
                              columns=['Region', 'Patient', 'Time',
                                       'Anccod', 'Mutcod',
                                       'Anc', 'Mut', 'Substitution',
                                       'Ssub',
                                       'Class', 'Trclass', 'af'])

    # Print some basic output
    if pnames is not None:
        title = ' + '.join(pnames)+',\n'+' + '.join(regions)
    else:
        title = ' + '.join(regions)

    for indices in (['Class', 'Trclass'],
                    ['Class', 'Substitution']):

        print_info(data['aft'], indices, title=title)


        # Fit change in time (mutation rate?)
        meangrouped = data['aft'].groupby(indices + ['Time']).mean()['af']
        pdata = meangrouped.unstack('Time')

    mu = get_mutation_rates(data['aft'], type='syn')
    print mu

    # Get accumulation rate in subtype entropy classes
    Sbins = [[0, 0.05], [0.05, 0.3], [0.3, 2]]
    muS = []
    for Sbin in Sbins:
        ind = (data['aft']['Ssub'] > Sbin[0]) & (data['aft']['Ssub'] <= Sbin[1])
        datum = data['aft'].loc[ind]
        mutmp = get_mutation_rates(datum, type='syn')
        mutmp.name = str(Sbin)
        muS.append(mutmp)

    muS = pd.concat(muS, axis=1)
    muS.name = 'synonymous mutation rate'
    print muS

    print comparison_Abram2010(mu)
    
    plot_mu_matrix(mu)

    if plot:
        for indices in [['Class', 'Trclass']]:

            # Plot the mean only
            fig, ax = plt.subplots()
            ax.set_title(title, fontsize=10)

            # Fit change in time (mutation rate?)
            meangrouped = data['aft'].groupby(indices + ['Time']).mean()['af']
            pdata = meangrouped.unstack('Time')

            for icl, (keys, arr) in enumerate(pdata.iterrows()):

                # Vary both color and line type instead of only color
                color = cm.jet(1.0 * icl / len(pdata))

                x = arr.index
                y = np.array(arr)

                # Linear LS fit (shall we do it on all data instead?)
                m = np.inner(x, y) / np.inner(x, x)

                ax.scatter(x, y, lw=2, color=color)

                xfit = np.linspace(x.min(), x.max(), 1000)
                ax.plot(xfit, m * xfit,
                        lw=2,
                        ls='-',
                        label=', '.join(keys)+' '+'{:1.1e}'.format(m)+' changes/day',
                        color=color)

            ax.grid(True)
            ax.legend(loc=2, fontsize=10)
            ax.set_xlabel('Time [days from infection]')
            ax.set_ylabel('Allele frequency')
            ax.set_yscale('log')
            ax.set_ylim(1e-4, 1)
            plt.tight_layout()

        plt.ion()
        plt.show()
