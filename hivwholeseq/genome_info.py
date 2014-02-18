# vim: fdm=marker
'''
author:     Fabio Zanini
date:       17/12/13
content:    Information module on the HIV genome.
'''
# Globals
genes = ('gag', 'pol', 'env', 'vif', 'vpr', 'vpu', 'tat', 'rev')

# Edges of genes (fuzzy)
gag_edges = ['ATGGGTGCGAGAGCGTCAGTA', 'GACCCCTCGTCACAATAA']
pol_edges = ['TTTTTTAGGGAAAATTTG', 'ACAGGATGAGGATTAG']
env_edges = ['ATGAGAGTGANGGNGANNNNGANGA',
             'GAAAGGGCTTTGCTATAA']
vif_edges = ['ATGGAAAACAGATGGCAGGTGA', 'ACAATGAATGGACACTAG']
vpr_edges = ['ATGGAACAAGCCCCAGAAGACCAG', 'AGATCCTAA']
vpu_edges = ['ATGCAACCTATACCAATAGTAGCAATAGTAGCATTAGTAGTAGCAATAATAATAGCAATAGTTGTGTGGTCC',             
             'GGGATGTTGATGATCTGTAG']
tat_edges = ['ATGGAGCCAGTAGATCCTAACC', 'ATCAAAGCA',
             'ACCCAC', 'TTCGATTAG']
rev_edges = ['ATGGCAGGAAGAAGC', 'ATCAAAGCA',
             'ACCCAC', 'GGAACTAAAGAATAG']

gene_edges = {'gag': gag_edges,
              'pol': pol_edges,
              'env': env_edges,
              'vif': vif_edges,
              'vpr': vpr_edges,
              'vpu': vpu_edges,
              'tat': tat_edges,
              'rev': rev_edges}

# Edges of RNA structures
RRE_edges = ['AGGAGCTATGTTCCTTGGGT', 'ACCTAAGGGATACACAGCTCCT']
LTR5 = ['', 'CTCTAGCA']

RNA_structure_edges = {'RRE': RRE_edges,
                       "LTR5'": LTR5}


# Edges of other regions
env_peptide_edges = ['ATGAGAGTGAAGGAGAA', 'TGTAGTGCT']
psi_element = ['CTCGGCTTGCT', 'AGCGGAGGCTAG']

other_edges = {'env peptide': env_peptide_edges,
               'psi': psi_element}



# Functions
def find_region_edges(smat, edges):
    '''Find a region's edges in a sequence'''
    import numpy as np

    pos_edge = []

    # Gene start
    emat = np.fromstring(edges[0], 'S1')
    n_matches = [(emat == smat[pos: pos+len(emat)]).sum()
                 for pos in xrange(len(smat) - len(emat))]
    pos = np.argmax(n_matches)
    pos_edge.append(pos)

    # Gene end
    emat = np.fromstring(edges[1], 'S1')
    n_matches = [(emat == smat[pos: pos+len(emat)]).sum()
                 for pos in xrange(pos_edge[0], len(smat) - len(emat))]
    pos = np.argmax(n_matches) + pos_edge[0] + len(emat)
    pos_edge.append(pos)

    return pos_edge


def find_region_edges_multiple(smat, edges):
    '''Find a multiple region (e.g. split gene)'''
    import numpy as np

    pos = 0
    pos_edges = []

    for i in xrange(len(edges) / 2):
        edges_i = edges[2 * i: 2 * (i + 1)]
        pos_edge = find_region_edges(smat[pos:], edges_i)
        pos_edge = [p + pos for p in pos_edge]
        pos_edges.append(pos_edge)
        pos = pos_edge[-1]

    return pos_edges


# NOTE: duplicate of above, but more specific to genes
def locate_gene(refseq, gene, minimal_fraction_match='auto', VERBOSE=0,
                pairwise_alignment=False):
    '''Locate a gene in a sequence
    
    Parameters:
        - minimal_fraction_match: if no location with at least e.g. 66% matches
          is found, the gene edge is not found.
    '''
    import numpy as np

    gene_edge = gene_edges[gene]

    # Automatic precision detection
    if minimal_fraction_match == 'auto':
        # The end of vif is variable
        if gene in ['vif', 'vpu']:
            minimal_fraction_match = 0.60
        else:
            minimal_fraction_match = 0.75

    # Make a string out of refseq, whatever you get in
    refseq = ''.join(refseq) 
    refm = np.fromstring(refseq, 'S1')

    # Try out pairwise local alignment
    if pairwise_alignment:
        from seqanpy import align_local as aol
        
        # Start
        seed = gene_edge[0]
        (score, ali_seq, ali_gen) = aol(refseq, seed)
        if score > minimal_fraction_match * len(seed.replace('N', '')):
            start_found = True
            start = refseq.find(ali_seq.replace('-', ''))
        else:
            start_found = False
            start = 0

        # End
        seed = gene_edge[1]
        (score, ali_seq, ali_gen) = aol(refseq[start:], seed, score_gapopen=-100)
        if score > minimal_fraction_match * len(seed.replace('N', '')):
            end_found = True
            end = start + refseq.find(ali_seq.replace('-', '')) + len(seed)
        else:
            end_found = False
            end = len(refseq)

        import ipdb; ipdb.set_trace()

    else:

        # Find start
        start_found = True
        start = refseq.find(gene_edge[0])
        # If perfect match does not work, try imperfect
        if start == -1:
            seed = np.ma.array(np.fromstring(gene_edge[0], 'S1'))
            seed[seed == 'N'] = np.ma.masked
            sl = len(seed)
            n_match = np.array([(refm[i: i + sl] == seed).sum()
                                for i in xrange(len(refm) - sl)], int)
            pos_seed = np.argmax(n_match)
            # Check whether a high fraction of the comparable (i.e. not masked)
            # sites match the seed
            if n_match[pos_seed] > minimal_fraction_match * (-seed.mask).sum():
                start = pos_seed
            else:
                start = 0
                start_found = False
        
        # Find end
        end_found = True
        end = refseq[start + 100:].find(gene_edge[1])
        if end != -1:
            end += len(gene_edge[1])
        else:
            seed = np.ma.array(np.fromstring(gene_edge[1], 'S1'))
            seed[seed == 'N'] = np.ma.masked
            sl = len(seed)
            n_match = np.array([(refm[i: i + sl] == seed).sum()
                                for i in xrange(start + 100, len(refm) - sl)], int)
            pos_seed = np.argmax(n_match)
            if n_match[pos_seed] > minimal_fraction_match * (-seed.mask).sum():
                end = pos_seed + sl
            else:
                end = len(refseq) - start - 100
                end_found = False
        end += start + 100


    if VERBOSE:
        if start_found:
            print 'Gene start:', start,
        else:
            print 'Gene start not found',

        if end_found:
            print 'Gene end:', end
        else:
            print 'Gene end not found'

    if (not start_found) and (not end_found):
        start = end = -1

    return (start, end, start_found, end_found)
