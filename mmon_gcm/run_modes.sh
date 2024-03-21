#!/bin/bash

# Define the lists of variables
LIGHT_COLOURS=("blue" "white" "nops")
ATPASE_CONSTRAINTS=("True" "False")
STARCH_KNOCKOUTS=("True" "False")

OUTPUT_DIR="../outputs/alternative_weighting"
MODEL_DIR="../models/4_stage_GC.json"
WEIGHTS_CSV="../outputs/alternative_weighting/alternative_weights.csv"
PARAMETERS_CSV="../inputs/arabidopsis_parameters.csv"

# Define dictionaries for translating ATPase_constrained and starch_knockout
declare -A ATPASE_TRANSLATION=( ["True"]="constrained" ["False"]="unconstrained" )
declare -A STARCH_TRANSLATION=( ["True"]="ko" ["False"]="wt" )

NO_CORES=$1

# Outer loop: Iterate over LIGHT_COLOURS
for LIGHT_COLOUR in "${LIGHT_COLOURS[@]}"; do
    # Middle loop: Iterate over ATPASE_CONSTRAINTS
    for ATPASE_CONSTRAINT in "${ATPASE_CONSTRAINTS[@]}"; do
        # Middle loop: Translate ATPase_constraint value
        ATPASE_TRANSLATED="${ATPASE_TRANSLATION[$ATPASE_CONSTRAINT]}"

        # Inner loop: Iterate over STARCH_KNOCKOUTS
        for STARCH_KNOCKOUT in "${STARCH_KNOCKOUTS[@]}"; do
            # Inner loop: Translate starch_knockout value
            STARCH_TRANSLATED="${STARCH_TRANSLATION[$STARCH_KNOCKOUT]}"

            # Create the OUTPUT_DIR_SPECIFIC variable
            OUTPUT_DIR_SPECIFIC="${OUTPUT_DIR}/${LIGHT_COLOUR}_${ATPASE_TRANSLATED}_${STARCH_TRANSLATED}.csv"

	    echo "$OUTPUT_DIR_SPECIFIC"

	    # python runalternativemodes.py "$OUTPUT_DIR_SPECIFIC" "$MODEL_DIR" "$WEIGHTS_CSV" "$PARAMETERS_CSV" "$LIGHT_COLOUR" "$ATPASE_CONSTRAINT" "$STARCH_KNOCKOUT" "$NO_CORES"

        done
    done
done

LIGHT_COLOUR="blue"
ATPASE_CONSTRAINT="True"
STARCH_KNOCKOUT="False"

OUTPUT_DIR_SPECIFIC="${OUTPUT_DIR}/${LIGHT_COLOUR}_${ATPASE_TRANSLATED}_${STARCH_TRANSLATED}.csv"
python runalternativemodes.py "$OUTPUT_DIR_SPECIFIC" "$MODEL_DIR" "$WEIGHTS_CSV" "$PARAMETERS_CSV" "$LIGHT_COLOUR" "$ATPASE_CONSTRAINT" "$STARCH_KNOCKOUT" "$NO_CORES"

