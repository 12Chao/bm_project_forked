"""
This script runs 15 simulations (each corresponding to a different starting
ratio) in Cantera.
Reactor conditions are replicated from: "Methane catalytic partial oxidation on
autothermal Rh and Pt foam catalysts: Oxidation and reforming zones, transport
effects,and approach to thermodynamic equilibrium"
Horn 2007, doi:10.1016/j.jcat.2007.05.011
Ref 17: "Syngas by catalytic partial oxidation of methane on rhodium:
Mechanistic conclusions from spatially resolved measurements and numerical
simulations"
Horn 2006, doi:10.1016/j.jcat.2006.05.008
Ref 18: "Spatial and temporal profiles in millisecond partial oxidation
processes"
Horn 2006, doi:10.1007/s10562-006-0117-8
"""
import cantera as ct
import numpy as np
import scipy
import pylab
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.pyplot import cm
from matplotlib.ticker import NullFormatter, MaxNLocator, LogLocator
plt.switch_backend('agg')  # needed for saving figures
import csv
import os
import re
import operator
import pandas as pd
import pylab
from cycler import cycler
import seaborn as sns
import os
import multiprocessing
from functools import partial
import threading
import itertools
import pandas as pd

# unit conversion factors to SI
mm = 0.001
cm = 0.01
ms = mm
minute = 60.0

#######################################################################
# Input Parameters
#######################################################################
t_in = 800  # K - in the paper, it was ~698.15K at the start of the cat surface and ~373.15 for the gas inlet temp
t_cat = t_in
length = 70 * mm  # Reactor length - m
diam = 16.5 * mm  # Reactor diameter - in m, from Ref 17 & Ref 18
area = (diam/2.0)**2*np.pi  # Reactor cross section area (area of tube) in m^2
porosity = 0.81  # Monolith channel porosity, from Ref 17, sec 2.2.2
cat_area_per_vol = 1.6e4  # m2/m3, which is 160 cm2/cm3, as used in Horn 2006
cat_area_per_vol *= 0.05 # to make the concentrations change slower
flow_rate = 4.7  # slpm, as seen in Horn 2007
tot_flow = 0.208  # constant inlet flow rate in mol/min, equivalent to 4.7 slpm
flow_rate = flow_rate * .001 / 60  # m^3/s, as seen in Horn 2007
velocity = flow_rate / area  # m/s

# The PFR will be simulated by a chain of 'N_reactors' stirred reactors.
N_reactors = 7001

on_catalyst = 1000  # catalyst length 10mm, from Ref 17
off_catalyst = 2000
dt = 1.0

reactor_len = length/(N_reactors-1)
rvol = area * reactor_len * porosity

# catalyst area in one reactor
cat_area = cat_area_per_vol * rvol

residence_time = reactor_len / velocity # unit in s

# root directory for output files
out_root = '/work/westgroup/chao/sketches/cpox_sim/bm_models_final/base_original/binding_energies/19.0_c-6.00o-3.25'

def setup_ct_solution(path_to_cti):

    # this chemkin file is from the cti generated by rmg
    gas = ct.Solution(path_to_cti, 'gas')
    surf = ct.Interface(path_to_cti, 'surface1', [gas])

    print("This mechanism contains {} gas reactions and {} surface reactions".format(gas.n_reactions, surf.n_reactions))
    print(f"Thread ID from threading{threading.get_ident()}")
    i_ar = gas.species_index('Ar')


    return {'gas':gas, 'surf':surf,"i_ar":i_ar,"n_surf_reactions":surf.n_reactions}


def change_species_enthalpy(surf, spec, dH, T):
    """
    change a species' enthlapy by dH (in J/kmol)
    """
    species = surf.species(spec)
    print(f"Initial H({T}) = {species.thermo.h(T)/1e6:.1f} kJ/mol")
    dx = dH / ct.gas_constant  # 'dx' is in fact (delta H / R). Note that R in cantera is 8314.462 J/kmol
    assert isinstance(species.thermo, ct.NasaPoly2)
    perturbed_coeffs = species.thermo.coeffs.copy()
    perturbed_coeffs[6] += dx
    perturbed_coeffs[13] += dx
    
    species.thermo = ct.NasaPoly2(species.thermo.min_temp, species.thermo.max_temp, 
                            species.thermo.reference_pressure, perturbed_coeffs)
    surf.modify_species(spec, species)
    print(f"Modified H({T}) = {species.thermo.h(T)/1e6:.1f} kJ/mol")


def monolith_simulation(path_to_cti, temp, mol_in, rtol, atol, verbose=False, sens=False, therm_sens=False):
    """
    Set up and solve the monolith reactor simulation.
    Verbose prints out values as you go along
    Sens is for sensitivity, in the form [perturbation, reaction #]
    Args:
        path_to_cti: full path to the cti file
        temp (float): The temperature in Kelvin
        mol_in (3-tuple or iterable): the inlet molar ratios of (CH4, O2, He)
        verbose (Boolean): whether to print intermediate results
        sens (False or 2-tuple/list): if not False, then should be a 2-tuple or list [dk, rxn]
                in which dk = relative change (eg. 0.01) and rxn = the index of the surface reaction rate to change
       therm_sens (False or 2-tuple/list): if not False, then should be a 2-tuple or list [dH, spc]
               in which dH = enthalpy change (J/kmol) and spc = the index of the surface species thermo to change
    Returns:
        gas_out, # gas molar flow rate in moles/minute
        surf_out, # surface mole fractions
        gas_names, # gas species names
        surf_names, # surface species names
        dist_array, # distances (in mm)
        T_array # temperatures (in K)
    """
    sols_dict = setup_ct_solution(path_to_cti)
    gas, surf, i_ar, n_surf_reactions= sols_dict['gas'], sols_dict['surf'], sols_dict['i_ar'],sols_dict['n_surf_reactions']
    print(f"Running monolith simulation with CH4 and O2 concs {mol_in[0], mol_in[1]} on thread {threading.get_ident()}")
    
    if therm_sens:
        change_species_enthalpy(surf, spec=therm_sens[1], dH=therm_sens[0], T=temp)
         
    ch4, o2, ar = mol_in
    ratio = ch4 / (2 * o2)

    X = f"CH4(2):{ch4}, O2(3):{o2}, Ar:{ar}"
    gas.TPX = 273.15, ct.one_atm, X  # need to initialize mass flow rate at STP
    mass_flow_rate = flow_rate * gas.density_mass # kg/s
    gas.TPX = temp, ct.one_atm, X
    temp_cat = temp
    surf.TP = temp_cat, ct.one_atm
    surf.coverages = 'X(1):1.0'
    gas.set_multiplier(1.0)

    TDY = gas.TDY
    cov = surf.coverages

    if verbose is True:
        print('  distance(mm)   X_CH4        X_O2        X_H2       X_CO       X_H2O       X_CO2')

    # create a new reactor
    gas.TDY = TDY
    r = ct.IdealGasReactor(gas)
    r.volume = rvol

    # create a reservoir to represent the reactor immediately upstream. Note
    # that the gas object is set already to the state of the upstream reactor
    upstream = ct.Reservoir(gas, name='upstream')

    # create a reservoir for the reactor to exhaust into. The composition of
    # this reservoir is irrelevant.
    downstream = ct.Reservoir(gas, name='downstream')

    # Add the reacting surface to the reactor. The area is set to the desired
    # catalyst area in the reactor.
    rsurf = ct.ReactorSurface(surf, r, A=cat_area)

    # The mass flow rate into the reactor will be fixed by using a
    # MassFlowController object.
    # mass_flow_rate = velocity * gas.density_mass * area  # kg/s
    # mass_flow_rate = flow_rate * gas.density_mass
    m = ct.MassFlowController(upstream, r, mdot=mass_flow_rate)

    # We need an outlet to the downstream reservoir. This will determine the
    # pressure in the reactor. The value of K will only affect the transient
    # pressure difference.
    v = ct.PressureController(r, downstream, master=m, K=1e-5)

    sim = ct.ReactorNet([r])
    sim.max_err_test_fails = 12

    # set relative and absolute tolerances on the simulation
    sim.rtol = rtol
    sim.atol = atol

    gas_names = gas.species_names
    surf_names = surf.species_names
    gas_out = []
    surf_out = []
    dist_array = []
    T_array = []

    surf.set_multiplier(0.0)  # no surface reactions until the gauze
    for n in range(N_reactors):
        # Set the state of the reservoir to match that of the previous reactor
        gas.TDY = r.thermo.TDY
        upstream.syncState()
        if n == on_catalyst:
            surf.set_multiplier(1.0)
            if sens is not False:
                surf.set_multiplier(1.0 + sens[0], sens[1])
        if n == off_catalyst:
            surf.set_multiplier(0.0)
        sim.reinitialize()
        # sim.advance_to_steady_state()
        sim.advance(sim.time + 1e4 * residence_time)
        dist = n * reactor_len * 1.0e3  # distance in mm
        dist_array.append(dist)
        T_array.append(surf.T)
        kmole_flow_rate = mass_flow_rate / gas.mean_molecular_weight  # kmol/s
        gas_out.append(1000 * 60 * kmole_flow_rate * gas.X.copy())  # molar flow rate in moles/minute
        surf_out.append(surf.X.copy())

        # stop simulation when things are done changing, to avoid getting so many COVDES errors
        if n >= 1001:
            if np.max(abs(np.subtract(gas_out[-2], gas_out[-1]))) < 1e-15:
                break

        if verbose is True:
            if not n % 100:
                print('  {0:10f}  {1:10f}  {2:10f}  {3:10f} {4:10f} {5:10f} {6:10f}'.format(dist, *gas[
                    'CH4(2)', 'O2(3)', 'H2(6)', 'CO(7)', 'H2O(5)', 'CO2(4)'].X * 1000 * 60 * kmole_flow_rate))

    gas_out = np.array(gas_out)
    surf_out = np.array(surf_out)
    data_out = gas_out, surf_out, gas_names, surf_names, dist_array, T_array, i_ar, n_surf_reactions
    print(len(dist_array))
    print(f"Finished monolith simulation for CH4 and O2 concs {mol_in[0], mol_in[1]} on thread {threading.get_ident()}")
    return data_out

def run_one_simulation(path_to_cti, rtol, atol, therm_sens, ratio):
    """
    Start all of the simulations all at once using multiprocessing
    """
    fo2 = 1 / (2. * ratio + 1 + 79. / 21.)
    fch4 = 2 * fo2 * ratio
    far = 79 * fo2 / 21
    ratio_in = [fch4, fo2, far]  # mol fractions
    
    try:
        a = monolith_simulation(path_to_cti, t_in, ratio_in, rtol, atol, therm_sens=therm_sens)
        gas_out, surf_out, gas_names, surf_names, dist_array, T_array, i_ar, n_surf_reactions = a 
        
        # Save the data to csv File
        tol_path = f'rtol_{rtol}_atol_{atol}/{ratio}'
        if not os.path.isdir(tol_path):
            os.makedirs(tol_path)
        data_path = os.path.join(tol_path, f'therm_sens_{therm_sens[1]}.csv')
        df_gas = pd.DataFrame(gas_out, columns=gas_names)
        df_surf = pd.DataFrame(surf_out, columns=surf_names)
        df = pd.concat([df_gas, df_surf], axis=1)
        df.insert(0, 'T(K)', T_array)
        df.insert(0, 'Distance(mm)', dist_array)
        df.to_csv(data_path)
    except ct.CanteraError:
        print(f'Simulation failed at {ratio}, {rtol}, {atol}, species {therm_sens[1]}')

if __name__ == "__main__":
    rtols = [1.0e-10, 1.0e-9, 1.0e-8, 1.0e-7, 1.0e-6, 1.0e-5]
    atols = [1.0e-20, 1.0e-18, 1.0e-16, 1.0e-14, 1.0e-12, 1.0e-10]
    tol_comb = []
    for index in range(len(rtols)):
        tol_comb.append([rtols[index], atols[index]])
    sols = setup_ct_solution('cantera.yaml')
    sp_num = sols['surf'].n_species
    for tols in tol_comb:
        ratios = [.6, 1., 1.1, 1.2, 1.6, 2., 2.6]
        data = []
        dH = 0.05 * 96491566. # 0.05 eV converted to J/kmol
        for i in range(sp_num):
            num_threads = min(multiprocessing.cpu_count(), len(ratios))
            pool = multiprocessing.Pool(processes=num_threads)
            pool.map(partial(run_one_simulation, 'cantera.yaml', tols[0], tols[1], (dH, i)), ratios, 1)
            pool.close()
            pool.join()
        