from autode.log import logger
import numpy as np
from scipy.optimize import minimize
from autode.config import Config
from autode.substitution import get_cost_rotate_translate
from autode.bond_rearrangement import get_bond_rearrangs
from autode.substitution import get_substitution_centres
from autode.reactions import Substitution, Elimination
from autode.bond_lengths import get_avg_bond_length
from autode.complex import ReactantComplex, ProductComplex
from autode.transition_states.ts_guess import get_template_ts_guess
from autode.transition_states.truncation import is_worth_truncating
from autode.transition_states.truncation import get_truncated_complex
from autode.pes_1d import get_ts_guess_1d
from autode.pes_2d import get_ts_guess_2d
from autode.methods import get_hmethod
from autode.methods import get_lmethod
from autode.transition_states.transition_state import TransitionState


def find_tss(reaction):
    """Find all the possible the transition states of a reaction

    Arguments:
        reaction (list(autode.reaction.Reaction)): Reaction

    Returns:
        list: list of transition state objects
    """
    logger.info('Finding possible transition states')

    reactant, product = ReactantComplex(*reaction.reacs, name='r'), ProductComplex(*reaction.prods, name='p')
    bond_rearrangs = get_bond_rearrangs(reactant, product, name=reaction.name)

    if bond_rearrangs is None:
        logger.error('Could not find a set of forming/breaking bonds')
        return None

    tss = []
    for bond_rearrangement in bond_rearrangs:
        logger.info(f'Locating transition state using active bonds {bond_rearrangement.all}')
        ts = get_ts(reaction, reactant, product, bond_rearrangement)

        if ts is not None:
            tss.append(ts)

    if len(tss) > 0:
        logger.info(f'Found *{len(tss)}* transition state(s) that lead to products')
        return tss

    logger.error('Did not find any transition state(s)')
    return None


def get_ts_guess_function_and_params(reaction, reactant, product, bond_rearr):
    """Get the functions (1dscan or 2dscan) and parameters required for the function for a TS scan

    Args:
        reaction (autode.reaction.Reaction):
        reactant (autode.complex.ReactantComplex):
        product (autode.complex.ProductComplex):
        bond_rearr (autode.bond_rearrangement.BondRearrangement):

    Returns:
        (list): updated funcs and params list
    """
    name = f'{reaction.name}_{"+".join([r.name for r in reaction.reacs])}--{"+".join([p.name for p in reaction.prods])}'

    lmethod, hmethod = get_lmethod(), get_hmethod()

    # Ideally use a transition state template, then only a single constrained optimisation need to be run..
    yield get_template_ts_guess, (reactant, product, bond_rearr, hmethod, hmethod.keywords.low_opt)

    # Otherwise run 1D or 2D potential energy surface scans to generate a transition state guess cheap -> most expensive
    if bond_rearr.n_bbonds == 1 and bond_rearr.n_fbonds == 1 and reaction.type in (Substitution, Elimination):
        bbond = bond_rearr.bbonds[0]
        fbond = bond_rearr.fbonds[0]

        scan_name = name + f'_{fbond[0]}-{fbond[1]}_{bbond[0]}-{bbond[1]}'
        bbond_final_dist = reactant.get_distance(atom_i=bbond[0], atom_j=bbond[1]) + get_added_bbond_dist(reaction)
        fbond_final_dist = get_avg_bond_length(atom_i_label=reactant.atoms[fbond[0]].label,
                                               atom_j_label=reactant.atoms[fbond[1]].label)

        yield get_ts_guess_2d, (reactant, product, fbond, bbond, 12, f'{scan_name}_ll2d', lmethod,
                                lmethod.keywords.low_opt, fbond_final_dist, bbond_final_dist)

        yield get_ts_guess_1d, (reactant, product, bbond, 12, f'{scan_name}_hl1d_bbond', hmethod,
                                hmethod.keywords.low_opt, bbond_final_dist)

        yield get_ts_guess_1d, (reactant, product, bbond, 12, f'{scan_name}_hl1d_opt_level_bbond',
                                hmethod, hmethod.keywords.opt, bbond_final_dist)

    if bond_rearr.n_bbonds > 0 and bond_rearr.n_fbonds == 1:
        fbond = bond_rearr.fbonds[0]
        scan_name = name + f'_{fbond[0]}-{fbond[1]}'
        fbond_final_dist = get_avg_bond_length(atom_i_label=reactant.atoms[fbond[0]].label,
                                               atom_j_label=reactant.atoms[fbond[1]].label)

        yield get_ts_guess_1d, (reactant, product, fbond, 10, f'{scan_name}_hl1d_fbond', hmethod,
                                hmethod.keywords.low_opt, fbond_final_dist)

        yield get_ts_guess_1d, (reactant, product, fbond, 12, f'{scan_name}_hl1d_opt_level_fbond', hmethod,
                                hmethod.keywords.opt, fbond_final_dist)

    if bond_rearr.n_bbonds >= 1 and bond_rearr.n_fbonds >= 1:
        for fbond in bond_rearr.fbonds:
            for bbond in bond_rearr.bbonds:
                scan_name = name + f'_{fbond[0]}-{fbond[1]}_{bbond[0]}-{bbond[1]}'

                fbond_final_dist = get_avg_bond_length(atom_i_label=reactant.atoms[fbond[0]].label,
                                                       atom_j_label=reactant.atoms[fbond[1]].label)
                bbond_final_dist = reactant.get_distance(atom_i=bbond[0], atom_j=bbond[1]) + get_added_bbond_dist(reaction)

                yield get_ts_guess_2d, (reactant, product, fbond, bbond, 12, f'{scan_name}_ll2d', lmethod,
                                        lmethod.keywords.low_opt, fbond_final_dist, bbond_final_dist)

                yield get_ts_guess_2d, (reactant, product, fbond, bbond, 8, f'{scan_name}_hl2d', hmethod,
                                        hmethod.keywords.low_opt, fbond_final_dist, bbond_final_dist, 3)

    if bond_rearr.n_bbonds == 1 and bond_rearr.n_fbonds == 0:
        bbond = bond_rearr.bbonds[0]
        scan_name = name + f'_{bbond[0]}-{bbond[1]}'
        bbond_final_dist = reactant.get_distance(atom_i=bbond[0], atom_j=bbond[1]) + get_added_bbond_dist(reaction)

        yield get_ts_guess_1d, (reactant, product, bbond, 12, f'{scan_name}_hl1d',
                                hmethod, hmethod.keywords.low_opt, bbond_final_dist)

        yield get_ts_guess_1d, (reactant, product, bbond, 12, f'{scan_name}_hl1d_opt_level', hmethod,
                                hmethod.keywords.opt, bbond_final_dist)

    if bond_rearr.n_fbonds == 2:
        fbond1, fbond2 = bond_rearr.fbonds
        scan_name = name + f'_{fbond1[0]}-{fbond1[1]}_{fbond2[0]}-{fbond2[1]}'

        fbond_final_dist1 = get_avg_bond_length(atom_i_label=reactant.atoms[fbond1[0]].label,
                                                atom_j_label=reactant.atoms[fbond1[1]].label)

        fbond_final_dist2 = get_avg_bond_length(atom_i_label=reactant.atoms[fbond2[0]].label,
                                                atom_j_label=reactant.atoms[fbond2[1]].label)

        yield get_ts_guess_2d, (reactant, product, fbond1, fbond2, 12, f'{scan_name}_ll2d_fbonds', lmethod,
                                lmethod.keywords.low_opt, fbond_final_dist1, fbond_final_dist2)
        yield get_ts_guess_2d, (reactant, product, fbond1, fbond2, 8, f'{scan_name}_hl2d_fbonds', hmethod,
                                hmethod.keywords.low_opt, fbond_final_dist1, fbond_final_dist2, 3)

    if bond_rearr.n_bbonds == 2:
        bbond1, bbond2 = bond_rearr.bbonds
        scan_name = name + f'_{bbond1[0]}-{bbond1[1]}_{bbond2[0]}-{bbond2[1]}'

        bbond1_final_dist = reactant.get_distance(atom_i=bbond1[0], atom_j=bbond2[1]) + get_added_bbond_dist(reaction) + get_added_bbond_dist(reaction)
        bbond2_final_dist = reactant.get_distance(atom_i=bbond1[0], atom_j=bbond2[1]) + get_added_bbond_dist(reaction) + get_added_bbond_dist(reaction)

        yield get_ts_guess_2d, (reactant, product, bbond1, bbond2, 12, f'{scan_name}_ll2d_bbonds', lmethod,
                                lmethod.keywords.low_opt, bbond1_final_dist, bbond2_final_dist)

        yield get_ts_guess_2d, (reactant, product, bbond1, bbond2, 8, f'{scan_name}_hl2d_bbonds', hmethod,
                                hmethod.keywords.low_opt, bbond1_final_dist, bbond2_final_dist, 3)

    return None


def translate_rotate_reactant(reactant, bond_rearrangement, shift_factor, n_iters=10):
    """
    Shift a molecule in the reactant complex so that the attacking atoms (a_atoms) are pointing towards the
    attacked atoms (l_atoms)

    Arguments:
        reactant (autode.complex.ReactantComplex):
        bond_rearrangement (autode.bond_rearrangement.BondRearrangement):
        shift_factor (float):
        n_iters (int): Number of iterations of translation/rotation to perform to (hopefully) find the global minima
    """
    if len(reactant.molecules) < 2:
        logger.info('Reactant molecule does not need to be translated or rotated')
        return

    logger.info('Rotating/translating the attacking molecule into a reactive conformation... running')

    subst_centres = get_substitution_centres(reactant, bond_rearrangement, shift_factor=shift_factor)
    attacking_mol = 0 if all(sc.a_atom in reactant.get_atom_indexes(mol_index=0) for sc in subst_centres) else 1

    # Disable the logger to prevent rotation/translations printing
    logger.disabled = True

    # Find the global minimum for inplace rotation, translation and rotation
    min_cost, opt_x = None, None

    for _ in range(n_iters):
        res = minimize(get_cost_rotate_translate, x0=np.random.random(11), method='BFGS', tol=0.1,
                       args=(reactant, subst_centres, attacking_mol))

        if min_cost is None or res.fun < min_cost:
            min_cost = res.fun
            opt_x = res.x

    # Renable the logger
    logger.disabled = False
    logger.info(f'Minimum cost for translating/rotating is {min_cost:.3f}')

    # Translate/rotation the attacking molecule optimally
    reactant.rotate_mol(axis=opt_x[:3], theta=opt_x[3], mol_index=attacking_mol)
    reactant.translate_mol(vec=opt_x[4:7], mol_index=attacking_mol)
    reactant.rotate_mol(axis=opt_x[7:10], theta=opt_x[10], mol_index=attacking_mol)

    logger.info('                                                                        ... done')
    reactant.print_xyz_file()

    return None


def get_truncated_ts(reaction, reactant, product, bond_rearr):
    """Get the TS of a truncated reactant and product complex"""

    # Truncate the reactant and product complex to the core atoms so the full TS can be template-d
    t_reactant = get_truncated_complex(reactant, bond_rearrangement=bond_rearr)
    t_product = get_truncated_complex(product, bond_rearrangement=bond_rearr)

    # Re-find the bond rearrangements, which really should exist as it it just a cut down reactant complex
    reaction.name += '_truncated'
    bond_rearrangs = get_bond_rearrangs(t_reactant, t_product, name=reaction.name)

    for bond_rearr in bond_rearrangs:
        get_ts(reaction, t_reactant, t_product, bond_rearrangement=bond_rearr, strip_molecule=False)

    reaction.name -= '_truncated'

    logger.info('Done with truncation')
    return None


def get_ts(reaction, reactant, product, bond_rearrangement, strip_molecule=True):
    """For a bond rearrangement run 1d and 2d scans to find a TS

    Args:
        reaction (autode.reaction.Reaction):
        reactant (autode.complex.ReactantComplex):
        product (autode.complex.ProductComplex):
        bond_rearrangement (autode.bond_rearrangement.BondRearrangement):
        strip_molecule (bool, optional): If true then the molecule will try and be stripped to make the scan
                                         calculations faster. The whole TS can the be found from the template made.
                                         Defaults to True.
    Returns:
        (autode.transition_states.transition_state.TransitionState):
    """
    # If specified then strip non-core atoms from the structure
    if strip_molecule and is_worth_truncating(reactant, bond_rearrangement):
        get_truncated_ts(reaction, reactant, product, bond_rearrangement)

    # If the reaction is a substitution or elimination then the reactants must be orientated correctly
    translate_rotate_reactant(reactant, bond_rearrangement,
                              shift_factor=3 if any(mol.charge != 0 for mol in reaction.reacs) else 1.5)

    # There are multiple methods of finding a transtion state. Iterate through from the cheapest -> most expensive
    for func, params in get_ts_guess_function_and_params(reaction, reactant, product, bond_rearrangement):
        logger.info(f'Trying to find a TS guess with {func.__name__}')
        ts_guess = func(*params)

        if ts_guess is None:
            continue

        if not ts_guess.could_have_correct_imag_mode(bond_rearrangement=bond_rearrangement):
            continue

        # Form a transition state object and run an OptTS calculation
        ts = TransitionState(ts_guess, bond_rearrangement=bond_rearrangement)
        ts.opt_ts()

        if not ts.is_true_ts():
            continue

        # Save a transition state template if specified in the config
        if Config.make_ts_template:
            ts.save_ts_template(folder_path=Config.ts_template_folder_path)

        logger.info(f'Found a transition state with {func.__name__}')
        return ts

    return None


def get_added_bbond_dist(reaction):
    """Get the bond length a breaking bond should increase by

    Args:
        reaction (reaction object): reaction being scanned

    Returns:
        float: distance the bond should increase by
    """
    # if there are charged molecules and implicit solvation, the bond length may need to increase by more to get a
    # saddle point,
    # as implicit solvation does not fully stabilise the charged molecule

    # TODO reimplement with explicit solvent like:   if reaction is SolvatedReaction

    if any(mol.charge != 0 for mol in reaction.prods):
        return 2.5
    else:
        return 1.5
