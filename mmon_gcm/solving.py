# AUTOGENERATED! DO NOT EDIT! File to edit: ../src/functions/solving.ipynb.

# %% auto 0
__all__ = ['pfba_Weighted', 'add_pfba_Weighted', 'get_weightings', 'flux_variability_analysis', 'pFBA_FVA_run',
           'get_sum_of_fluxes', 'rev2irrev', 'check_fba_fva_run', 'get_pfba_fva_solution']

# %% ../src/functions/solving.ipynb 3
from itertools import chain

import numpy as np
import pandas as pd
from cobra import flux_analysis
from cobra.core.solution import get_solution
from cobra.util import solver as sutil
from .buildingediting import check_number_of_models
from optlang.symbolics import Zero

from cobra.flux_analysis.variability import _init_worker, _fva_step

import logging
from typing import TYPE_CHECKING, List, Optional, Set, Tuple, Union
from warnings import warn

from cobra.util import ProcessPool

import time
from datetime import datetime

# %% ../src/functions/solving.ipynb 5
def pfba_Weighted(
    model, weightings=None, fraction_of_optimum=1.0, objective=None, reactions=None
):
    """Perform basic pFBA (parsimonious Enzyme Usage Flux Balance Analysis)
    to minimize total flux.
    pFBA [1] adds the minimization of all fluxes the the objective of the
    model. This approach is motivated by the idea that high fluxes have a
    higher enzyme turn-over and that since producing enzymes is costly,
    the cell will try to minimize overall flux while still maximizing the
    original objective function, e.g. the growth rate.

    ##### Parameters:
    model : cobra.Model
        The model
    fraction_of_optimum : float, optional
        Fraction of optimum which must be maintained. The original objective
        reaction is constrained to be greater than maximal_value *
        fraction_of_optimum.
    objective : dict or model.problem.Objective
        A desired objective to use during optimization in addition to the
        pFBA objective. Dictionaries (reaction as key, coefficient as value)
        can be used for linear objectives.
    reactions : iterable
        List of reactions or reaction identifiers. Implies `return_frame` to
        be true. Only return fluxes for the given reactions. Faster than
        fetching all fluxes if only a few are needed.

    ##### Returns:
    cobra.Solution

    The solution object to the optimized model with pFBA constraints added.

    References:
    .. [1] Lewis, N. E., Hixson, K. K., Conrad, T. M., Lerman, J. A.,
       Charusanti, P., Polpitiya, A. D., Palsson, B. O. (2010). Omic data
       from evolved E. coli are consistent with computed optimal growth from
       genome-scale models. Molecular Systems Biology, 6,
       390. doi:10.1038/msb.2010.47
    """
    reactions = (
        model.reactions if reactions is None else model.reactions.get_by_any(reactions)
    )
    tempmodel = model.copy()
    with tempmodel as m:
        add_pfba_Weighted(
            m, weightings, objective=objective, fraction_of_optimum=fraction_of_optimum
        )
        m.slim_optimize(error_value=None)
        solution = get_solution(m, reactions=reactions)
    return m, solution

# %% ../src/functions/solving.ipynb 7
def add_pfba_Weighted(model, weightings=None, objective=None, fraction_of_optimum=1.0):
    """
    This function is a modified version of cobrapy add_pfba function

    Add pFBA objective
    Add objective to minimize the summed flux of all reactions to the
    current objective.

    See Also:
    pfba

    Parameters:
    model : cobra.Model
        The model to add the objective to
    objective :
        An objective to set in combination with the pFBA objective.
    fraction_of_optimum : float
        Fraction of optimum which must be maintained. The original objective
        reaction is constrained to be greater than maximal_value *
        fraction_of_optimum.
    """
    if weightings == None:
        weightings = get_weightings(model)
    if objective is not None:
        model.objective = objective
    if model.solver.objective.name == "_pfba_objective":
        raise ValueError("The model already has a pFBA objective.")
    sutil.fix_objective_as_constraint(model, fraction=fraction_of_optimum)
    reaction_variables = (
        (rxn.forward_variable, rxn.reverse_variable) for rxn in model.reactions
    )
    variables = chain(*reaction_variables)
    model.objective = model.problem.Objective(
        Zero, direction="min", sloppy=True, name="_pfba_objective"
    )
    # print([v for v in variables])
    tempDict = dict()
    for v in variables:
        w = str(v).split("=")[1].replace(" ", "").replace("<", "")
        found = False
        for rxn in weightings.keys():
            if w.__contains__(rxn):
                tempDict[v] = weightings[rxn]
                found = True
                break
        if not found:
            print(
                "Weightings for reaction " + w + " not found, so assuming weighting = 1"
            )
            tempDict[v] = 1
    model.objective.set_linear_coefficients(tempDict)

# %% ../src/functions/solving.ipynb 9
def get_weightings(model):
    """
    This function is used by pfba_weighted to generate default weightings for the guard cell model
    It takes the model as an argument and returns the weightings based on the phase lengths of the model.
    """
    weightings = {}
    number_of_models = check_number_of_models(model)
    for i in range(1, number_of_models + 1):
        length_of_phase = 1 / (
            -model.reactions.get_by_id(f"SUCROSE_v_gc_Linker_{i}").get_coefficient(
                f"SUCROSE_v_gc_{i}"
            )
        )
        for reaction in model.reactions:
            if (
                "constraint" in reaction.id
                or "overall" in reaction.id
                or "sum" in reaction.id
                or reaction.id[:2] == "EX"
            ):
                weightings[reaction.id] = 0
            elif reaction.id[-1] == str(i):
                weightings[reaction.id] = length_of_phase
    return weightings

# %% ../src/functions/solving.ipynb 11
def flux_variability_analysis(
    model,
    reaction_list: Optional[List[Union["Reaction", str]]] = None,
    loopless: bool = False,
    fraction_of_optimum: float = 1.0,
    pfba_factor: Optional[float] = None,
    processes: Optional[int] = None,
) -> pd.DataFrame:
    """Determine the minimum and maximum flux value for each reaction.

    Parameters
    ----------
    model : cobra.Model
        The model for which to run the analysis. It will *not* be modified.
    reaction_list : list of cobra.Reaction or str, optional
        The reactions for which to obtain min/max fluxes. If None will use
        all reactions in the model (default None).
    loopless : bool, optional
        Whether to return only loopless solutions. This is significantly
        slower. Please also refer to the notes (default False).
    fraction_of_optimum : float, optional
        Must be <= 1.0. Requires that the objective value is at least the
        fraction times maximum objective value. A value of 0.85 for instance
        means that the objective has to be at least at 85% percent of its
        maximum (default 1.0).
    pfba_factor : float, optional
        Add an additional constraint to the model that requires the total sum
        of absolute fluxes must not be larger than this value times the
        smallest possible sum of absolute fluxes, i.e., by setting the value
        to 1.1 the total sum of absolute fluxes must not be more than
        10% larger than the pFBA solution. Since the pFBA solution is the
        one that optimally minimizes the total flux sum, the `pfba_factor`
        should, if set, be larger than one. Setting this value may lead to
        more realistic predictions of the effective flux bounds
        (default None).
    processes : int, optional
        The number of parallel processes to run. If not explicitly passed,
        will be set from the global configuration singleton (default None).

    Returns
    -------
    pandas.DataFrame
        A data frame with reaction identifiers as the index and two columns:
        - maximum: indicating the highest possible flux
        - minimum: indicating the lowest possible flux

    Notes
    -----
    This implements the fast version as described in [1]_. Please note that
    the flux distribution containing all minimal/maximal fluxes does not have
    to be a feasible solution for the model. Fluxes are minimized/maximized
    individually and a single minimal flux might require all others to be
    sub-optimal.

    Using the loopless option will lead to a significant increase in
    computation time (about a factor of 100 for large models). However, the
    algorithm used here (see [2]_) is still more than 1000x faster than the
    "naive" version using `add_loopless(model)`. Also note that if you have
    included constraints that force a loop (for instance by setting all fluxes
    in a loop to be non-zero) this loop will be included in the solution.

    References
    ----------
    .. [1] Computationally efficient flux variability analysis.
       Gudmundsson S, Thiele I.
       BMC Bioinformatics. 2010 Sep 29;11:489.
       doi: 10.1186/1471-2105-11-489, PMID: 20920235

    .. [2] CycleFreeFlux: efficient removal of thermodynamically infeasible
       loops from flux distributions.
       Desouki AA, Jarre F, Gelius-Dietrich G, Lercher MJ.
       Bioinformatics. 2015 Jul 1;31(13):2159-65.
       doi: 10.1093/bioinformatics/btv096.

    """
    if reaction_list is None:
        reaction_ids = [r.id for r in model.reactions]
    else:
        reaction_ids = [r.id for r in model.reactions.get_by_any(reaction_list)]

    if processes is None:
        processes = configuration.processes

    num_reactions = len(reaction_ids)
    processes = min(processes, num_reactions)

    fva_result = pd.DataFrame(
        {
            "minimum": np.zeros(num_reactions, dtype=float),
            "maximum": np.zeros(num_reactions, dtype=float),
        },
        index=reaction_ids,
    )
    prob = model.problem
    with model:
        # Safety check before setting up FVA.
        model.slim_optimize(
            error_value=None,
            message="There is no optimal solution for the chosen objective!",
        )
        # Add the previous objective as a variable to the model then set it to
        # zero. This also uses the fraction to create the lower/upper bound for
        # the old objective.
        # TODO: Use utility function here (fix_objective_as_constraint)?
        if model.solver.objective.direction == "max":
            fva_old_objective = prob.Variable(
                "fva_old_objective",
                lb=fraction_of_optimum * model.solver.objective.value,
            )
        else:
            fva_old_objective = prob.Variable(
                "fva_old_objective",
                ub=fraction_of_optimum * model.solver.objective.value,
            )
        fva_old_obj_constraint = prob.Constraint(
            model.solver.objective.expression - fva_old_objective,
            lb=0,
            ub=0,
            name="fva_old_objective_constraint",
        )
        model.add_cons_vars([fva_old_objective, fva_old_obj_constraint])

        if pfba_factor is not None:
            if pfba_factor < 1.0:
                warn(
                    "The 'pfba_factor' should be larger or equal to 1.",
                    UserWarning,
                )
            with model:
                add_pfba(model, fraction_of_optimum=0)
                ub = model.slim_optimize(error_value=None)
                flux_sum = prob.Variable("flux_sum", ub=pfba_factor * ub)
                flux_sum_constraint = prob.Constraint(
                    model.solver.objective.expression - flux_sum,
                    lb=0,
                    ub=0,
                    name="flux_sum_constraint",
                )
            model.add_cons_vars([flux_sum, flux_sum_constraint])

        model.objective = Zero  # This will trigger the reset as well
        for what in ("minimum", "maximum"):
            if processes > 1:
                # We create and destroy a new pool here in order to set the
                # objective direction for all reactions. This creates a
                # slight overhead but seems the most clean.
                chunk_size = len(reaction_ids) // processes
                with ProcessPool(
                    processes,
                    initializer=_init_worker,
                    initargs=(model, loopless, what[:3]),
                ) as pool:
                    for rxn_id, value in pool.imap_unordered(
                        _fva_step, reaction_ids, chunksize=chunk_size
                    ):
                        print(rxn_id)
                        fva_result.at[rxn_id, what] = value
            else:
                _init_worker(model, loopless, what[:3])
                for rxn_id, value in map(_fva_step, reaction_ids):
                    fva_result.at[rxn_id, what] = value

    return fva_result[["minimum", "maximum"]]

# %% ../src/functions/solving.ipynb 12
def pFBA_FVA_run(cobra_model, obj, rxnlist=[], processes=3, fix_sof_for_fva=False):

    print("Running pFBA")
    cobra_model, solution = pfba_Weighted(cobra_model, objective=obj)
    # pfba_model = cobra_model.copy()
    objvalue = solution.get_primal_by_id(obj)

    if fix_sof_for_fva == True:

        sum_of_fluxes = get_sum_of_fluxes(cobra_model)

        # get the weightings for SOF and generate a copy of the model that, where weightings are not zero and the reaction is reversible,
        # splits the reaction into a forwards and reverse reaction and makes them both irreversible
        weightings = get_weightings(cobra_model)
        cobra_model2 = cobra_model.copy()
        irr_model = rev2irrev(cobra_model2)
        print("Setting SOF model")

        # set the weightings for the reverse reactions to be the same as the forward reactions
        for reaction in irr_model.reactions:
            if reaction.id.__contains__("_reverse"):
                id = reaction.id
                originalreaction = id.replace("_reverse", "")
                weightings[reaction.id] = weightings[originalreaction]

        # weight the forward and reverse reactions of the reactions, whether they are forward or reverse, equally for SOF.
        # Add a constraint to the model that the sum of these reactions with their coefficients cannot be different to the sum_of_fluxes from pFBA
        coefficients = {}
        for reaction in irr_model.reactions:
            coefficients[reaction.forward_variable] = weightings[reaction.id]
            coefficients[reaction.reverse_variable] = weightings[reaction.id]
        sofconstraint = irr_model.problem.Constraint(
            0, lb=sum_of_fluxes, ub=sum_of_fluxes, name="sofconstraint"
        )
        irr_model.add_cons_vars(sofconstraint)
        irr_model.solver.update()
        sofconstraint.set_linear_coefficients(coefficients=coefficients)

        new_coefficients = coefficients.copy()
        sum_of_fluxes = irr_model.problem.Variable("sum_of_fluxes")
        new_coefficients[sum_of_fluxes] = -1
        sofvariableconstraint = irr_model.problem.Constraint(0, lb=0, ub=0)
        irr_model.add_cons_vars([sum_of_fluxes, sofvariableconstraint])
        irr_model.solver.update()
        sofvariableconstraint.set_linear_coefficients(coefficients=new_coefficients)

        # fix objective to be equal to pFBA
        phloemconstraint = irr_model.problem.Constraint(
            irr_model.reactions.get_by_id(obj).flux_expression,
            lb=objvalue,
            ub=objvalue,
            name="phloem_output",
        )
        irr_model.add_cons_vars(phloemconstraint)

        irr_model.optimize()

        sfmodel = irr_model.copy()

        rxnlist2 = []

        # if rxnlist is not empty, add just the forward reaction if it isn't reversible or add both forward and reverse if it is
        for rxn in rxnlist:
            rxn = sfmodel.reactions.get_by_id(rxn.id)
            if rxn.lower_bound < 0 and rxn.upper_bound > 0 and weightings[rxn.id] != 0:
                rxnlist2.append(sfmodel.reactions.get_by_id(rxn.id + "_reverse"))
            rxnlist2.append(sfmodel.reactions.get_by_id(rxn.id))

        print("Running FVA")

        fva = flux_analysis.flux_variability_analysis(sfmodel, reaction_list=rxnlist2, processes=processes)
        print("Processing results")

        fva2 = dict()
        for mode in fva.keys():
            if mode == "maximum":
                tempdict = dict()
                FVArxnSet = set()
                for rxn in fva[mode].keys():
                    if rxn.__contains__("_reverse"):
                        rxn = rxn.replace("_reverse", "")
                    if FVArxnSet.__contains__(rxn):
                        continue
                    FVArxnSet.add(rxn)
                    if not fva[mode].keys().__contains__(rxn + "_reverse"):
                        maxi = fva[mode][rxn]
                    else:
                        maxi = fva[mode][rxn] + fva[mode][rxn + "_reverse"]
                    tempdict[rxn] = maxi
            else:
                tempdict = dict()
                FVArxnSet = set()
                for rxn in fva[mode].keys():
                    if rxn.__contains__("_reverse"):
                        rxn = rxn.replace("_reverse", "")
                    if FVArxnSet.__contains__(rxn):
                        continue
                    FVArxnSet.add(rxn)
                    if not fva[mode].keys().__contains__(rxn + "_reverse"):
                        mini = fva[mode][rxn]
                    else:
                        mini = fva[mode][rxn] + fva[mode][rxn + "_reverse"]
                    tempdict[rxn] = mini
            fva2[mode] = tempdict

        cobra_model.fva = fva2

    else:
        if len(rxnlist) == 0:
            print("FVA list is empty")
        else:
            print(f"Running FVA on {len(rxnlist)} reactions using {processes} processes")

        fva = flux_variability_analysis(
            cobra_model, reaction_list=rxnlist, processes=processes, loopless=True)
        cobra_model.fva = fva

    return cobra_model, solution

# %% ../src/functions/solving.ipynb 14
def get_sum_of_fluxes(model):
    weightings = get_weightings(model)
    sum_of_fluxes = 0
    for reaction_id in weightings.keys():
        sum_of_fluxes = sum_of_fluxes + (
            abs(model.reactions.get_by_id(reaction_id).flux) * weightings[reaction_id]
        )
    return sum_of_fluxes

# %% ../src/functions/solving.ipynb 16
def rev2irrev(cobra_model):
    """
    Function to convert any model with reversible reactions to a copy of the same m-
    -odel with only irreversible reactions. ID of reverse reactions are generated by
    suffixing "_reverse" to the ID of the orignal reaction.
    args: 1) a cobra model
    output: a cobra model with only irreversible reactions
    """
    exp_model = cobra_model.copy()
    for RXN in cobra_model.reactions:
        rxn = exp_model.reactions.get_by_id(RXN.id)
        if rxn.lower_bound < 0:
            rxn_reverse = rxn.copy()
            rxn_reverse.id = "%s_reverse" % (rxn.id)
            rxn.lower_bound = 0
            rxn_reverse.upper_bound = 0
            exp_model.add_reaction(rxn_reverse)

    return exp_model

# %% ../src/functions/solving.ipynb 18
def check_fba_fva_run(fba_model, pfba_solution):
    '''
    This is a test that checks if the fluxes that are returned 
    by the fba model are different to those by the pFBA
    '''
    fva_fluxes = np.array(
        [reaction.flux for reaction in fba_model.reactions]
    )
    if len(pfba_solution[pfba_solution.fluxes - fva_fluxes != 0]) > 0:
        return False
    else:
        return True

# %% ../src/functions/solving.ipynb 20
def get_pfba_fva_solution(
    fba_model, rxn_list=[], objective="Phloem_tx_overall", processes=3, fix_sof_for_fva=False
):
    """Take FBA model and solve weighted FVA on a list of reactions. 
    Returns a dataframe with flux of all reactions and minimum and 
    maximum if they were in the fva list"""

    start = time.time()
    start_datetime = datetime.fromtimestamp(start)
    print(f"Started running pFBA (and FVA) @ {start_datetime}")

    
    fba_model, pfba_solution = pFBA_FVA_run(
        fba_model, objective, rxnlist=rxn_list, processes=processes, fix_sof_for_fva=fix_sof_for_fva
    )

    end = time.time()
    end_datetime = datetime.fromtimestamp(end)

    print(f"Finished running pFBA (and FVA) @ {end_datetime}, that took {(end - start)/60} minutes")

    pfba_df = pfba_solution.to_frame().loc[:, "fluxes":"fluxes"]
    fva_df = pd.DataFrame(fba_model.fva)

    combined_df = pfba_df.join(fva_df)

    #assert(check_fba_fva_run(fba_model, pfba_solution))

    return fba_model, combined_df
