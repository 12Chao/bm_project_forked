"""
This file is for averaging the simulation characters in different tolerances
"""

import pandas as pd
import numpy as np
import os
from pathlib import Path 

# find the paths of all the csv files
f_paths = []
# rtols = [1.0e-10, 1.0e-9, 1.0e-8, 1.0e-7, 1.0e-6, 1.0e-5]
# atols = [1.0e-20, 1.0e-18, 1.0e-16, 1.0e-14, 1.0e-12, 1.0e-10]
rtols = [1.0e-9, 1.0e-8]
atols = [1.0e-18, 1.0e-16]
# rxn_id = int(os.getenv('SLURM_ARRAY_TASK_ID', default='0'))
rxn_id = int(os.getenv('SLURM_ARRAY_TASK_ID')) - 1

# total 107 reactions
for ratio in [.6, 1., 1.1, 1.2, 1.6, 2., 2.6]:
    sens_data = np.zeros((7001, 17))
    denominator = 0
    for i in range(len(rtols)):
        data_path = f'sens_trends/rtol_{rtols[i]}_atol_{atols[i]}/{ratio}/kin_sens_trend_{rxn_id}.csv'
        if os.path.exists(data_path):
            df = pd.read_csv(data_path)
            if len(df) >= 7000:
                sens_data += df
                denominator += 1
    if denominator != 0:
        sens_data /= denominator

    output_dir = Path(f"sens_trends/{ratio}/kin_sens_trend_avg_{rxn_id}.csv")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    table_names = ['Reactions', 'Ratio', 'SYNGAS Selec', 'SYNGAS Yield', 'CO Selectivity', 'CO % Yield', 'H2 Selectivity', 
                    'H2 % Yield', 'CH4 Conversion', 'H2O+CO2 Selectivity', 'H2O+CO2 yield', 'Exit Temp', 'Peak Temp',
                    'Dist to peak temp', 'O2 Conversion', 'Max CH4 Conv', 'Dist to 50 CH4 Conv']
    pd.DataFrame(sens_data, columns=table_names).to_csv(output_dir, index=False)
