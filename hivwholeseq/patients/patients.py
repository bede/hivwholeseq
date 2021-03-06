# vim: fdm=marker
'''
author:     Fabio Zanini
date:       23/10/13
content:    Description module for HIV patients.
'''
# Modules
import numpy as np
import pandas as pd

from hivwholeseq.sequencing.filenames import table_filename
from .samples import * # FIXME: lots of scripts import from here still
from ..data._secret import pdict as _pdict



# Globals
_pdict_back = dict(item[::-1] for item in _pdict.iteritems())



# Classes
class Patient(pd.Series):
    '''HIV patient'''

    def __init__(self, *args, **kwargs):
        '''Initialize a patient with all his samples'''
        super(Patient, self).__init__(*args, **kwargs)
        from hivwholeseq.patients.samples import load_samples_sequenced
        samples = load_samples_sequenced(patients=[self.name])
        self.samples = samples


    @property
    def _constructor(self):
        return Patient


    @property
    def folder(self):
        '''The folder with the data on this patient'''
        from hivwholeseq.patients.filenames import get_foldername
        return str(get_foldername(self.code))


    def discard_nonsequenced_samples(self):
        '''Discard all samples that have not been sequenced yet'''
        from hivwholeseq.sequencing.samples import load_samples_sequenced as lss
        samples_sequenced = lss()
        samples_sequenced_set = set(samples_sequenced.loc[:, 'patient sample']) - set(['nan'])
        samples = self.samples.loc[self.samples.index.isin(samples_sequenced_set)]

        ## Add info on sequencing
        ## FIXME: why is this here?!
        ## FIXME: this is buggy is so many ways... pandas is nto great at this
        #samples_seq_col = []
        #for samplename in samples.index:
        #    ind = samples_sequenced.loc[:, 'patient sample'] == samplename
        #    samples_seq_col.append(samples_sequenced.loc[ind])

        #samples.loc[:, 'samples seq'] = samples_seq_col

        self.samples = samples


    @property
    def dates(self):
        '''Get the dates of sampling'''
        return self.samples.date

    
    @property
    def times(self, unit='day'):
        '''Get the times from transmission'''
        ts = self.samples['days since infection']
        if unit == 'month':
            ts *= 1.0 / 30.5
        elif unit == 'year':
            ts *= 1.0 / 365.24
        return ts

        #return convert_date_deltas_to_float(self.dates - self.transmission_date, unit=unit)


    @property
    def viral_load(self):
        '''Get the time course of the viral load [molecules/ml of serum]'''
        return self.samples['viral load']


    @property
    def cell_count(self):
        '''Get the time course of the CD4+ cell count'''
        return self.samples['CD4+ count']


    @property
    def n_templates(self):
        '''Get the time course of the number of templates to PCR, limiting depth'''
        from hivwholeseq.patients.get_template_number import get_template_number
        n = [get_template_number(dilstr) for dilstr in self.samples.dilutions]
        n = np.ma.masked_invalid(n)
        return n


    @property
    def n_templates_viral_load(self):
        '''Get the number of templates, estimated from the viral load'''
        n = self.viral_load.copy()
        # We take 400 ul of serum
        n *= 0.4
        # We typically have 6 reactions with that total volume (plus the F4 dilution
        # series, but each of those uses only 0.1x template which is very little)
        n /= 6.1
        return n


    def get_n_templates_roi(self, roi):
        '''Get number of templates, roi specific from overlap frequencies'''
        fragments = self.get_fragments_covered(roi)
        n = [min(sample[fr+'q'] for fr in fragments)
             for _, sample in self.samples.iterrows()]
        n = np.ma.masked_invalid(n)
        return n


    @property
    def initial_sample(self):
        '''The initial sample used as a mapping reference'''
        from .samples import SamplePat
        return SamplePat(self.samples.iloc[0])


    def itersamples(self):
        '''Generator for samples in this patient, each with extended attributes'''
        from hivwholeseq.patients.samples import SamplePat
        for samplename, sample in self.samples.iterrows():
            yield SamplePat(sample)


    def get_fragmented_roi(self, roi, VERBOSE=0, **kwargs):
        '''Get a region of interest in fragment coordinates'''
        from .get_roi import get_fragmented_roi
        if isinstance(roi, basestring):
            roi = (roi, 0, '+oo')
        refseq = self.get_reference('genomewide', 'gb')
        return get_fragmented_roi(refseq, roi, VERBOSE=VERBOSE, **kwargs)

    
    def get_fragments_covered(self, roi, VERBOSE=0):
        '''Get the list of fragments interested by this roi'''
        from .get_roi import get_fragments_covered
        return get_fragments_covered(self, roi, VERBOSE=VERBOSE)


    def get_reference_filename(self, fragment, format='fasta'):
        '''Get filename of the reference for mapping'''
        from hivwholeseq.patients.filenames import get_initial_reference_filename
        return get_initial_reference_filename(self.name, fragment, format)


    def get_reference(self, region, format='fasta'):
        '''Get the reference for a genomic region'''
        from Bio import SeqIO
        fragments = ['F'+str(i) for i in xrange(1, 7)] + ['genomewide']

        if region in fragments:
            fragment = region
        else:
            (fragment, start, end) = self.get_fragmented_roi((region, 0, '+oo'),
                                                             include_genomewide=True)

        refseq = SeqIO.read(self.get_reference_filename(fragment, format=format),
                            format)

        if format in ('gb', 'genbank'):
            from hivwholeseq.utils.sequence import correct_genbank_features_load
            correct_genbank_features_load(refseq)

        if region not in fragments:
            refseq = refseq[start: end]

        return refseq


    def get_consensi_alignment_filename(self, region, format='fasta'):
        '''Get the filename of the multiple sequence alignment of all consensi'''
        from hivwholeseq.patients.filenames import get_consensi_alignment_filename
        return get_consensi_alignment_filename(self.name, region, format=format)


    def get_consensi_alignment(self, region, format='fasta'):
        '''Get the multiple sequence alignment of all consensi'''
        from Bio import AlignIO
        return AlignIO.read(self.get_consensi_alignment_filename(region,
                                                                 format=format),
                            format)


    def get_consensi_tree_filename(self, region, format='newick'):
        '''Get the filename of the consensi tree of the patient'''
        from hivwholeseq.patients.filenames import get_consensi_tree_filename
        return get_consensi_tree_filename(self.name, region, format=format)


    def get_consensi_tree(self, region, format='newick'):
        '''Get consensi tree from the patient'''
        import os.path

        if format == 'json':
            fn = self.get_consensi_tree_filename(region, format='json')
            if os.path.isfile(fn):
                from ..utils.generic import read_json
                from ..utils.tree import tree_from_json
                return tree_from_json(read_json(fn))

        fn = self.get_consensi_tree_filename(region, format='newick')
        if os.path.isfile(fn):
            from Bio import Phylo
            return Phylo.read(fn, 'newick')


    def get_local_tree_filename(self, region, format='json'):
        '''Get the filename of the consensi tree of the patient'''
        from hivwholeseq.patients.filenames import get_local_tree_filename
        return get_local_tree_filename(self.code, region, format=format)


    def get_local_tree(self, region):
        '''Get consensi tree from the patient'''
        from ..utils.generic import read_json
        from ..utils.tree import tree_from_json

        fn = self.get_local_tree_filename(region, format='json')
        return tree_from_json(read_json(fn))



    @staticmethod
    def get_initial_consensus_noinsertions(aft, VERBOSE=0, return_ind=False):
        '''Make initial consensus from allele frequencies, keep coordinates and masked
        
        Args:
          aft (np.ma.ndarray): 3d masked array with the allele frequency trajectories

        Returns:
          np.ndarray: initial consensus, augmented with later time points at masked
          positions, with Ns if never covered
        '''
        from ..utils.sequence import alpha

        af0 = aft[0]
        # Fill the masked positions with N...
        cons_ind = af0.argmax(axis=0)
        cons_ind[af0[0].mask] = 5
    
        # ...then look in later time points
        if aft.shape[0] == 1:
            if return_ind:
                return cons_ind
            else:
                return alpha[cons_ind]

        for af_later in aft[1:]:
            cons_ind_later = af_later.argmax(axis=0)
            cons_ind_later[af_later[0].mask] = 5
            ind_Ns = (cons_ind == 5) & (cons_ind_later != 5)
            cons_ind[ind_Ns] = cons_ind_later[ind_Ns]
        if return_ind:
            return cons_ind
        else:
            return alpha[cons_ind]


    def get_initial_allele_counts(self, fragment):
        '''Get allele counts from the initial time point'''
        import os
        from hivwholeseq.patients.samples import SamplePat
        for i in xrange(len(self.samples)):
            sample = SamplePat(self.samples.iloc[i])
            if os.path.isfile(sample.get_allele_counts_filename(fragment)):
                return sample.get_allele_counts(fragment)


    def get_initial_allele_frequencies(self, fragment, cov_min=1):
        '''Get the allele frequencies from the initial time point'''
        counts = self.get_initial_allele_counts(fragment)
        cov = counts.sum(axis=0)
        af = np.ma.masked_where(np.tile(cov < cov_min, (counts.shape[0], 1)), counts)
        af.harden_mask()
        af = 1.0 * af / af.sum(axis=0)
        return af


    def get_coverage_trajectories(self, region, **kwargs):
        '''Get coverage as a function of time'''
        (act, ind) = self.get_allele_count_trajectories(region, **kwargs)
        return (act.sum(axis=1), ind)


    def get_allele_frequency_trajectories(self, region,
                                          cov_min=1,
                                          depth_min=None,
                                          error_rate=2e-3,
                                          **kwargs):
        '''Get the allele frequency trajectories from files
        
        Args:
          region (str): region to study, a fragment or a genomic feature (e.g. V3)
          cov_min (int): minimal coverage accepted, anything lower are masked.
          depth_min (float): minimal depth, both by sequencing and template numbers.
            Time points with less templates are excluded, and positions are masked.
            For convenience depth is defined > 1, e.g. 100 takes frequencies down
            to 1%.
          **kwargs: passed down to the get_allele_count_trajectories method.
        '''
        (act, ind) = self.get_allele_count_trajectories(region, **kwargs)
        if depth_min is not None:
            # FIXME: use number of templates from the overlaps
            # if we require more than one fragment, take the min of the touched ones
            indd = np.array(self.n_templates[ind] >= depth_min)
            act = act[indd]
            ind = ind[indd]
            cov_min = max(cov_min, depth_min)

        covt = act.sum(axis=1)
        mask = np.zeros_like(act, bool)
        mask.swapaxes(0, 1)[:] = covt < cov_min

        # NOTE: the hard mask is necessary to avoid unmasking part of the alphabet
        # at a certain site: the mask is site-wise, not allele-wise
        aft = np.ma.array((1.0 * act.swapaxes(0, 1) / covt).swapaxes(0, 1),
                          mask=mask,
                          hard_mask=True,
                          fill_value=0)

        # The error rate is the limit of sensible minor alleles anyway
        aft[(aft < error_rate)] = 0

        # Renormalize
        aft = (aft.swapaxes(0, 1) / aft.sum(axis=1)).swapaxes(0, 1)

        return (aft, ind)


    def get_allele_frequency_trajectories_aa(self, protein, cov_min=1,
                                             depth_min=None, **kwargs):
        '''Get the allele frequency trajectories from files
        
        Args:
          region (str): region to study, a fragment or a genomic feature (e.g. V3)
          cov_min (int): minimal coverage accepted, anything lower are masked.
          depth_min (float): minimal depth, both by sequencing and template numbers.
            Time points with less templates are excluded, and positions are masked.
            For convenience depth is defined > 1, e.g. 100 takes frequencies down
            to 1%.
          **kwargs: passed down to the get_allele_count_trajectories method.
        '''
        (act, ind) = self.get_allele_count_trajectories_aa(protein, **kwargs)
        if depth_min is not None:
            # FIXME: use number of templates from the overlaps
            # if we require more than one fragment, take the min of the touched ones
            indd = np.array(self.n_templates[ind] >= depth_min)
            act = act[indd]
            ind = ind[indd]
            cov_min = max(cov_min, depth_min)

        covt = act.sum(axis=1)
        mask = np.zeros_like(act, bool)
        mask.swapaxes(0, 1)[:] = covt < cov_min

        # NOTE: the hard mask is necessary to avoid unmasking part of the alphabet
        # at a certain site: the mask is site-wise, not allele-wise
        aft = np.ma.array((1.0 * act.swapaxes(0, 1) / covt).swapaxes(0, 1),
                          mask=mask,
                          hard_mask=True,
                          fill_value=0)

        aft[(aft < 1e-4)] = 0
        # NOTE: we'd need to renormalize, but it's a small effect

        return (aft, ind)


    def get_insertion_trajectories(self, region, **kwargs):
        '''Get the trajectory of insertions'''
        from collections import Counter
        (fragment, start, end) = self.get_fragmented_roi((region, 0, '+oo'),
                                                         include_genomewide=True)
        ind = []
        ics = Counter()
        for i, sample in enumerate(self.itersamples()):
            time = sample['days since infection']
            try:
                ic = sample.get_insertions(region, **kwargs)
            except IOError:
                continue
            ind.append(i)
            for (position, insertion), value in ic.iteritems():
                ics[(time, position, insertion)] = value
        return (ics, ind)


    def get_allele_count_trajectories(self, region, safe=False, **kwargs):
        '''Get the allele count trajectories from files
        
        Args:
          region (str): region to study, a fragment or a genomic feature (e.g. V3)
          **kwargs: passed down to the function (VERBOSE, etc.).

        Note: the genomewide counts are currently saved to file.
        '''
        from operator import itemgetter
        from .one_site_statistics import get_allele_count_trajectories

        # Multi-location regions are special
        multi_location_regions = {'gp120_noVloops': 'F5'}
        if region in ['tat', 'rev']:
            raise NotImplementedError
        
        # NOTE: this logic is a bit redundant for the gp120_noVloops,
        # but can be readily extended to tat/rev in the future
        elif region in ['gp120_noVloops']:
            fragment = multi_location_regions[region]
            refseq = self.get_reference('genomewide', 'gb')
            frag_found = False
            reg_found = False
            for fea in refseq.features:
                if fea.id == region:
                    fea_reg = fea
                    reg_found = True
                elif fea.id == fragment:
                    fea_frag = fea
                    frag_found = True
                if reg_found and frag_found:
                    break

            else:
                raise ValueError('Region not found!')

            acts = []
            inds = []
            for part in fea.location.parts:
                start = part.nofuzzy_start - fea_frag.location.nofuzzy_start
                end = part.nofuzzy_end - fea_frag.location.nofuzzy_start
                (sns, act) = get_allele_count_trajectories(self.name, self.samples.index,
                                                           fragment,
                                                           use_PCR1=2, **kwargs)
                act = act[:, :, start: end]
                ind = np.array([i for i, (_, sample) in enumerate(self.samples.iterrows())
                                if sample.name in map(itemgetter(0), sns)], int)
                acts.append(act)
                inds.append(ind)

            # Take intersection of all time points
            ind = np.array(sorted(set.intersection(*map(set, inds))), int)
            if len(ind) == 0:
                act = np.array([])
            else:
                for iact, act in enumerate(acts):
                    indtmp = [ii for ii, i in enumerate(inds[iact]) if i in ind]
                    acts[iact] = act[indtmp]
                act = np.dstack(acts)        

        else:

            # Fall back on genomewide counts if no single fragment is enough
            (fragment, start, end) = self.get_fragmented_roi((region, 0, '+oo'),
                                                             include_genomewide=True)
            (sns, act) = get_allele_count_trajectories(self.name, self.samples.index,
                                                       fragment,
                                                       use_PCR1=2, **kwargs)
            # Select genomic region
            act = act[:, :, start: end]

            # Select time points
            ind = np.array([i for i, (_, sample) in enumerate(self.samples.iterrows())
                            if sample.name in map(itemgetter(0), sns)], int)

            # If safe, take only samples tagged with 'OK'
            if safe:
                ind_safe = np.zeros(len(ind), bool)
                for ii, i in enumerate(ind):
                    sample = self.samples.iloc[i]
                    frags = self.get_fragments_covered((fragment, start, end))
                    ind_safe[ii] = all(getattr(sample, fr).upper() == 'OK'
                                       for fr in frags)

                act = act[ind_safe]
                ind = ind[ind_safe]


        return (act, ind)


    def get_allele_count_trajectories_aa(self, protein, safe=False, **kwargs):
        '''Get the allele count trajectories from files
        
        Args:
          region (str): region to study, a fragment or a genomic feature (e.g. V3)
          **kwargs: passed down to the function (VERBOSE, etc.).

        Note: the genomewide counts are currently saved to file.
        '''
        from operator import itemgetter
        from .one_site_statistics import get_allele_count_trajectories_aa

        (sns, act) = get_allele_count_trajectories_aa(self.name, self.samples.index,
                                                      protein, **kwargs)

        # Select time points
        ind = np.array([i for i, (_, sample) in enumerate(self.samples.iterrows())
                        if sample.name in map(itemgetter(0), sns)], int)

        # If safe, take only samples tagged with 'OK'
        if safe:
            (fragment, start, end) = self.get_fragmented_roi(protein, VERBOSE=VERBOSE)
            ind_safe = np.zeros(len(ind), bool)
            for ii, i in enumerate(ind):
                sample = self.samples.iloc[i]
                frags = self.get_fragments_covered((fragment, start, end))
                ind_safe[ii] = all(getattr(sample, fr).upper() == 'OK'
                                   for fr in frags)

            act = act[ind_safe]
            ind = ind[ind_safe]


        return (act, ind)



    def get_mapped_filtered_filename(self, samplename, fragment, PCR=1):
        '''Get filename(s) of mapped and filtered reads for a sample'''
        from hivwholeseq.patients.filenames import get_mapped_filtered_filename
        return get_mapped_filtered_filename(self.patient, samplename, fragment, PCR=PCR)


    def get_divergence(self, region, **kwargs):
        '''Get genetic divergence of a region
        
        Args:
          **kwargs: passed to the allele frequency trajectories.
        '''
        from hivwholeseq.patients.get_divergence_diversity import get_divergence
        aft, ind = self.get_allele_frequency_trajectories(region, **kwargs)
        return (get_divergence(aft), ind)


    def get_diversity(self, region, **kwargs):
        '''Get geneticdiversity of a region
        
        Args:
          **kwargs: passed to the allele frequency trajectories.
        '''
        from hivwholeseq.patients.get_divergence_diversity import get_diversity
        aft, ind = self.get_allele_frequency_trajectories(region, **kwargs)
        return (get_diversity(aft), ind)


    def get_divergence_trajectory_local(self, region, block_length=150, **kwargs):
        '''Get local divergence trajectory'''
        from hivwholeseq.patients.get_divergence_diversity_local import (
            get_divergence_trajectory_local)
        return get_divergence_trajectory_local(self.code, region,
                                               block_length=block_length)


    def get_diversity_trajectory_local(self, region, block_length=150, **kwargs):
        '''Get local diversity trajectory'''
        from hivwholeseq.patients.get_divergence_diversity_local import (
            get_diversity_trajectory_local)
        return get_diversity_trajectory_local(self.code, region,
                                              block_length=block_length)


    @property
    def transmission_date(self):
        '''The most likely time of transmission'''
        return self['last negative date'] + \
                (self['first positive date'] - self['last negative date']) / 2


    def get_map_coordinates_reference_filename(self, fragment, refname='HXB2'):
        '''Get the filename of the coordinate map to an external reference'''
        from hivwholeseq.patients.filenames import get_coordinate_map_filename
        return get_coordinate_map_filename(self.name, fragment, refname=refname)


    def get_map_coordinates_reference(self, roi, refname='HXB2'):
        '''Get the map of coordinate to some external reference

        Parameters:
          refname (string or (string, string)): name of the reference or pair with
            both the reference name and the region name. The latter version shifts
            the reference coordinate with respect to the region start
        
        Returns:
          comap (2D int array): the first column are the positions in the reference,
            the second column the position in the patient initial reference. 
        '''
        if isinstance(roi, basestring):
            region = roi
        else:
            region = roi[0]

        if not isinstance(refname, basestring):
            refregion = refname[1]
            refname = refname[0]
        else:
            refregion = None

        fn = self.get_map_coordinates_reference_filename(region, refname=refname)
        mapco = np.loadtxt(fn, dtype=int)

        if refregion is not None:
            from ..reference import load_custom_reference
            refseq = load_custom_reference(refname, 'gb')
            for feature in refseq.features:
                if feature.id == refregion:
                    startref = feature.location.nofuzzy_start
                    mapco[:, 0] -= startref
                    break

        if isinstance(roi, basestring):
            return mapco
        else:
            start = roi[1]
            ind = (mapco[:, 1] >= start)

            if roi[2] != '+oo':
                end = roi[2]
                ind &= (mapco[:, 1] < end)

            # The patient coordinates are referred to the roi itself!
            mapco[:, 1] -= start
            return mapco[ind]


    def get_local_haplotype_trajectories(self, region, start, end, VERBOSE=0,
                                         **kwargs):
        '''Get trajectories of local haplotypes
        
        Parameters:
           region (str): genomic region or fragment
           start (int): start position in region
           end (int): end position in region ('+oo': end of the region)
        '''
        if region in ['F'+str(i) for i in xrange(1, 7)]:
            fragment = region
        else:
            (fragment, start, end) = self.get_fragmented_roi((region, start, end),
                                                             VERBOSE=VERBOSE)

        ind = []
        haplos = []
        for i, sample in enumerate(self.itersamples()):
            try:
                haplo = sample.get_local_haplotypes(fragment, start, end,
                                                    VERBOSE=VERBOSE,
                                                    **kwargs)
            except IOError:
                continue

            # Discard time points with zero coverage
            if len(haplo):
                haplos.append(haplo)
                ind.append(i)

        return (haplos, ind)


    def get_local_haplotype_count_trajectories(self,
                                               region, start=0, end='+oo',
                                               VERBOSE=0,
                                               align=False,
                                               return_dict=False,
                                               **kwargs):
        '''Get trajectories of local haplotypes counts
        
        Parameters:
           region (str): genomic region or fragment
           start (int): start position in region
           end (int): end position in region ('+oo': end of the region)
        '''
        (haplos, ind) = self.get_local_haplotype_trajectories(region,
                                                              start, end,
                                                              VERBOSE=VERBOSE,
                                                              **kwargs)
        # Make trajectories of counts
        seqs_set = set()
        for haplo in haplos:
            seqs_set |= set(haplo.keys())
        seqs_set = list(seqs_set)
        hct = np.zeros((len(seqs_set), len(haplos)), int)
        for i, haplo in enumerate(haplos):
            for seq, count in haplo.iteritems():
                hct[seqs_set.index(seq), i] = count

        # Sometimes you collect no haplotype at all (too wide or unlucky regions)
        if not len(seqs_set):
            L = 1
        else:
            L = np.max(map(len, seqs_set))

        seqs_set = np.array(seqs_set, 'S'+str(L))

        if align:
            from ..utils.sequence import align_muscle
            ali = align_muscle(*seqs_set, sort=True)
            alim = np.array(ali)
            
            if return_dict:
                return {'hct': hct,
                        'ind': ind,
                        'seqs': seqs_set,
                        'ali': ali,
                        'alim': alim,
                       } 

            return (hct.T, ind, seqs_set, ali)

        if return_dict:
            return {'hct': hct,
                    'ind': ind,
                    'seqs': seqs_set,
                   } 

        return (hct.T, ind, seqs_set)

    
    def get_haplotype_count_trajectory_filename(self, region):
        '''Get filename of the haplotype count trajectory in a genomic region'''
        from .filenames import get_haplotype_count_trajectory_filename
        return get_haplotype_count_trajectory_filename(self.code, region)


    def get_haplotype_count_trajectory(self, region, aligned=True):
        '''Get precompiled haplotype count trajectory in a genomic region
        
        Returns:
            (hct, ind, seqs): triple,
                hct (matrix of int): counts (n. time points, n. haplotypes)
                ind (array of int): indices for the time points
                seqs (list or matrix): sequences or alignment of haplotypes
            aligned (bool): get an alignment of the sequences or the raw ones
        '''
        import numpy as np
        data = np.load(self.get_haplotype_count_trajectory_filename(region))
        if aligned:
            return (data['hct'], data['ind'], data['ali'])
        else:
            return (data['hct'], data['ind'], data['seqs'])


    def get_haplotype_alignment_filename(self, region, format='fasta'):
        '''Get filename of the alignment of haplotypes in a genomic region'''
        from .filenames import get_haplotype_alignment_filename
        return get_haplotype_alignment_filename(self.name, region, format=format)


    def get_hla_type(self, MHC=1):
        '''Get a list with all HLA loci
        
        Parameters:
           MHC (None/1/2): MHC class I/II only, or all
        '''
        if MHC == 1:
            loci = ('A', 'B', 'C')
        elif MHC == 2:
            loci = ('DRB1', 'DRQ1')
        else:
            loci = ('A', 'B', 'C', 'DRB1', 'DRQ1')

        hla = np.concatenate([[locus+self['HLA-'+locus],
                               locus+self['HLA-'+locus+'-2']]
                              for locus in loci]).tolist()
        return hla


    def get_ctl_epitopes(self,
                         regions=['gag', 'pol',
                                  'gp120', 'gp41',
                                  'vif', 'vpr', 'vpu', 'nef'],
                         kind='epitoolkit',
                        ):
        '''Get list of CTL epitopes
        
        Parameters:
           regions (list): restrict to epitopes within these regions
           kind (str): LANL/epitoolkit/mhci=<n>, where <n> is the cutoff for
           the MHCi predicted list: the first <n> entries are taken.
        '''
        # Get epitope table for patient HLA
        if kind == 'LANL':
            from ..cross_sectional.ctl_epitope_map import (get_ctl_epitope_map,
                                                           get_ctl_epitope_hla)
            ctl_table_main = get_ctl_epitope_map(species='human')
            hla = self.get_hla_type(MHC=1)
            ctl_table_main = get_ctl_epitope_hla(ctl_table_main, hla)
            del ctl_table_main['HXB2 start']
            del ctl_table_main['HXB2 end']
            del ctl_table_main['HXB2 DNA Contig']
            del ctl_table_main['Protein']
            del ctl_table_main['Subprotein']

        elif 'mhci=' in kind:
            n_entries = int(kind[5:])
            def get_ctl_epitope_map_mhci(pcode):
                def get_ctl_epitope_map_filename(pcode):
                    from .filenames import root_data_folder
                    filename = root_data_folder+'CTL/mhci/ctl_'+pcode+'.tsv'
                    return filename

                import pandas as pd
                table = pd.read_csv(get_ctl_epitope_map_filename(pcode),
                                    skiprows=3,
                                    sep='\t',
                                    usecols=['peptide'],
                                    # NOTE: top epitopes only, this is a parameter
                                    nrows=n_entries,
                                   )
                table.drop_duplicates(inplace=True)

                table.rename(columns={'peptide': 'Epitope'}, inplace=True)
                return table

            ctl_table_main = get_ctl_epitope_map_mhci(self.code)

        elif kind == 'epitoolkit':
            def get_ctl_epitope_map_epitoolkit(pcode):
                def get_ctl_epitope_map_filenames(pcode):
                    import glob
                    from .filenames import root_data_folder
                    blobname = root_data_folder+'CTL/epitoolkit/ctl_'+pcode+'/*.csv'
                    return glob.glob(blobname)

                import pandas as pd
                table = pd.concat([pd.read_csv(fn,
                                               skiprows=1,
                                               sep=',',
                                               usecols=['Sequence'],
                                              )
                                   for fn in get_ctl_epitope_map_filenames(pcode)])
                table.drop_duplicates(inplace=True)

                table.rename(columns={'Sequence': 'Epitope'}, inplace=True)
                return table

            ctl_table_main = get_ctl_epitope_map_epitoolkit(self.code)

        else:
            raise ValueError('kind of CTL table not understood')

        # Load HXB2 to set the coordinates
        from ..reference import load_custom_reference
        from ..utils.sequence import find_annotation
        ref = load_custom_reference('HXB2', 'gb')

        # Load patient reference for coordinates
        seqgw = self.get_reference('genomewide', 'gb')

        data = []
        for region in regions:

            # Restrict epitope table to founder virus sequence
            fea = find_annotation(seqgw, region)
            regpos = fea.location.nofuzzy_start
            seq = fea.extract(seqgw)
            prot = str(seq.seq.translate())
            ind = [i for i, epi in enumerate(ctl_table_main['Epitope']) if epi in prot]
            ctl_table = ctl_table_main.iloc[ind].copy()

            # Set position in region
            # NOTE: the same epitope could be there twice+ in a protein
            import re
            tmp = []
            for epi in ctl_table['Epitope']:
                for match in re.finditer(epi, prot):
                    pos = match.start()
                    tmp.append({'Epitope': epi,
                                'start_region': 3 * pos,
                                'end_region': 3 * (pos + len(epi)),
                               })
            ctl_table = pd.DataFrame(tmp)
            if not len(ctl_table):
                continue

            # Set position genomewide
            ctl_table['start'] = ctl_table['start_region'] + regpos
            ctl_table['end'] = ctl_table['end_region'] + regpos

            # Set position in HXB2
            regpos_HXB2 = find_annotation(ref, region).location.nofuzzy_start
            comap = dict(self.get_map_coordinates_reference(region)[:, ::-1], refname='HXB2')
            poss = []
            for x in ctl_table['start_region']:
                while True:
                    if x in comap:
                        poss.append(x)
                        break
                    elif x < 0:
                        poss.append(-1)
                        break
                    x -= 1
            ctl_table['start_HXB2'] = np.array(poss, int) + regpos_HXB2
            poss = []
            for x in ctl_table['end_region']:
                while True:
                    if x in comap:
                        poss.append(x)
                        break
                    elif x > 10000:
                        poss.append(-1)
                        break
                    x += 1
            ctl_table['end_HXB2'] = np.array(poss, int) + regpos_HXB2

            # Filter out epitopes for which we cannot find an HXB2 position
            ctl_table = ctl_table.loc[(ctl_table[['start_HXB2', 'end_HXB2']] != -1).all(axis=1)]

            ctl_table['region'] = region

            data.append(ctl_table)

        ctl_table = pd.concat(data).sort('start_HXB2')
        ctl_table.index = range(len(ctl_table))

        return ctl_table

        


# Functions
def iterpatient(patients):
    for pname, patient in patients.iterrows():
        yield (pname, Patient(patient))


def load_patients(pnames=None):
    '''Load patients from general table'''
    patients = pd.read_excel(table_filename, 'Patients', index_col=1)
    patients.index = pd.Index(map(str, patients.index))

    if pnames is not None:
        if 'p' in pnames[0]:
            pnames = [_pdict[pname] for pname in pnames]
        patients = patients.loc[pnames]
    return patients


def load_patient(pname):
    '''Get the patient from the sequences ones'''
    patients = load_patients()
    if pname in patients.index:
        patient = Patient(patients.loc[pname])
    else:
        patient = Patient(patients.loc[patients.code == pname].iloc[0])
    return patient


def filter_patients_n_times(patients, n_times=3):
    '''Find what patients have at least n_times time points sequenced'''
    ind = np.zeros(len(patients), bool)
    for i, (pname, patient) in enumerate(patients.iterrows()):
        patient = Patient(patient)
        patient.discard_nonsequenced_samples()
        if len(patient.times) >= n_times:
            ind[i] = True

    return ind


def convert_date_deltas_to_float(deltas, unit='day'):
    '''Convert pandas date deltas into float'''
    nanoseconds_per_unit = {'day': 3600e9 * 24,
                            'month': 3600e9 * 24 * 365.25 / 12,
                            'year': 3600e9 * 24 * 365.25,
                           }
    return np.array(deltas, float) / nanoseconds_per_unit[unit]


