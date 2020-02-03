import os
from subprocess import Popen
from autode.log import logger
from autode.exceptions import XYZsNotFound
from autode.exceptions import NoInputError
from autode.config import Config
from autode.methods import get_hmethod
from autode.methods import get_lmethod
from autode.solvent.solvents import get_available_solvents
from shutil import which


class Calculation:

    def _get_core_atoms(self, molecule):
        """Finds the atoms involved in the reaction, and those bonded to them. These atoms are then
        calculated exactly in the hybrid hessian, if a full exact hessian is not calculated

        Arguments:
            molecule (mol obj): the molecule being calculated
        """
        active_atoms = set()
        for bond in self.bond_ids_to_add:
            active_atoms.add(bond[0])
            active_atoms.add(bond[1])
        core_atoms = set()
        for active_atom in active_atoms:
            bonded_atoms = molecule.get_bonded_atoms_to_i(active_atom)
            core_atoms.add(active_atom)
            for bonded_atom in bonded_atoms:
                core_atoms.add(bonded_atom)
        self.core_atoms = list(core_atoms)

    def get_energy(self):
        logger.info(f'Getting energy from {self.output_filename}')
        if self.terminated_normally:
            return self.method.get_energy(self)

        else:
            logger.error('Calculation did not terminate normally – not returning the energy')
            return None

    def optimisation_converged(self):
        logger.info('Checking to see if the geometry converged')
        return self.method.optimisation_converged(self)

    def optimisation_nearly_converged(self):
        """Check whether a calculation has nearly converged and may just need more geometry optimisation steps to
        complete successfully

        Returns:
            bool: if the calc is nearly converged or not
        """
        return self.method.optimisation_nearly_converged(self)

    def get_imag_freqs(self):
        logger.info('Finding imaginary frequencies in cm-1')
        return self.method.get_imag_freqs(self)

    def get_normal_mode_displacements(self, mode_number):
        """Get the displacements along a mode for each of the n_atoms in the structure will return a list of length
        n_atoms each with 3 components (x, y, z)

        Arguments:
            mode_number (int): normal mode number. 6 will be the first vibrational mode (indexed from 0 in ORCA)

        Returns:
            list(list): list of displacement distances for each xyz
        """
        return self.method.get_normal_mode_displacements(self, mode_number)

    def get_final_xyzs(self):
        logger.info(f'Getting final xyzs from {self.output_filename}')
        xyzs = self.method.get_final_xyzs(self)

        if len(xyzs) == 0:
            logger.error(f'Could not get xyzs from calculation file {self.name}')
            raise XYZsNotFound

        return xyzs

    def calculation_terminated_normally(self):
        logger.info(f'Checking to see if {self.output_filename} terminated normally')
        if self.output_file_lines is None:
            return False
        return self.method.calculation_terminated_normally(self)

    def set_output_file_lines(self):
        self.output_file_lines = [line for line in open(self.output_filename, 'r', encoding="utf-8")]
        self.rev_output_file_lines = list(reversed(self.output_file_lines))
        return None

    def generate_input(self):
        logger.info(f'Generating input file for {self.name}')
        return self.method.generate_input(self)

    def execute_calculation(self):
        logger.info(f'Running calculation {self.input_filename}')

        if self.input_filename is None:
            logger.error('Could not run the calculation. Input filename not defined')
            raise NoInputError

        if self.method.available is False:

            logger.critical('Electronic structure method is not available')
            exit()

        if not os.path.exists(self.input_filename):
            logger.error('Could not run the calculation. Input file does not exist')
            return

        if os.path.exists(self.output_filename):
            self.output_file_exists = True
            self.set_output_file_lines()

        if self.output_file_exists:
            if self.calculation_terminated_normally():
                logger.info('Calculation already terminated successfully. Skipping')
                return self.set_output_file_lines()

        logger.info(f'Setting the number of OMP threads to {self.n_cores}')
        os.environ['OMP_NUM_THREADS'] = str(self.n_cores)

        with open(self.output_filename, 'w') as output_file:

            if self.method.mpirun:
                mpirun_path = which('mpirun')
                params = [mpirun_path, '-np', str(self.n_cores), self.method.path, self.input_filename]
            else:
                params = [self.method.path, self.input_filename]
            if self.flags is not None:
                params += self.flags

            subprocess = Popen(params, stdout=output_file,
                               stderr=open(os.devnull, 'w'))
        subprocess.wait()
        logger.info(f'Calculation {self.output_filename} done')

        for filename in os.listdir(os.getcwd()):
            name_string = '.'.join(self.input_filename.split('.')[:-1])
            if name_string in filename:
                if (not filename.endswith(('.out', '.hess', '.xyz', '.inp', '.com', '.log', '.nw'))) or filename.endswith(('.smd.out', '.drv.hess')):
                    os.remove(filename)

        logger.info('Deleting non-output files')

        return self.set_output_file_lines()

    def run(self):
        logger.info(f'Running calculation of {self.name}')

        self.generate_input()
        self.execute_calculation()
        self.terminated_normally = self.calculation_terminated_normally()

        return None

    def __init__(self, name, molecule, method, keywords=None, n_cores=1, max_core_mb=1000, bond_ids_to_add=None,
                 optts_block=None, opt=False, distance_constraints=None, cartesian_constraints=None, constraints_already_met=False):
        """
        Arguments:
            name (str): calc name
            molecule (molecule object): molecule to be calculated
            method (method object): which electronic structure wrapper to use

        Keyword Arguments:
            keywords (calc keywords): keywords to use in the calc (default: {None})
            n_cores (int): number of cores available (default: {1})
            max_core_mb (int): max mb per core (default: {1000})
            bond_ids_to_add (list(tuples)): list of active bonds (default: {None})
            optts_block (list): keywords to use when performing a TS search (default: {None})
            opt (bool): opt calc or not (needed for XTB) (default: {False})
            distance_constraints (dict): keys = tuple of atom ids for a bond to be kept at fixed length, value = length to be fixed at (default: {None})
            cartesian_constraints (list(int)): list of atom ids to fix at their cartesian coordinates (default: {None})
            constraints_already_met (bool): if the constraints are already met, or need optimising to (needed for XTB force constant) (default: {False})
        """
        self.name = name
        self.xyzs = molecule.xyzs
        self.charge = molecule.charge
        self.mult = molecule.mult
        self.method = method
        self.keywords = keywords
        self.flags = None
        self.opt = opt
        self.core_atoms = None

        self.solvent = molecule.solvent

        self.n_cores = n_cores
        # Maximum memory per core to use
        self.max_core_mb = max_core_mb

        self.bond_ids_to_add = bond_ids_to_add
        self.optts_block = optts_block
        self.distance_constraints = distance_constraints
        self.cartesian_constraints = cartesian_constraints
        self.constraints_already_met = constraints_already_met

        # Set in self.generate_input()
        self.input_filename = None
        # Set in self.generate_input()
        self.output_filename = None

        self.output_file_exists = False
        self.terminated_normally = False
        self.output_file_lines = None
        self.rev_output_file_lines = None

        if molecule.solvent is not None:
            if getattr(molecule.solvent, method.__name__) is False:
                logger.critical('Solvent is not available. Cannot run the calculation')
                hmethod = get_hmethod()
                lmethod = get_lmethod()
                print(f'Available solvents for {hmethod.__name__} as the higher level method and {lmethod.__name__} as the lower level method are {get_available_solvents(hmethod.__name__, lmethod.__name__)}')
                exit()

        self.solvent_keyword = getattr(molecule.solvent, method.__name__)

        if self.xyzs is None:
            logger.error('Have no xyzs. Can\'t make a calculation')
            return

        if self.bond_ids_to_add:
            self._get_core_atoms(molecule)

        self.n_atoms = len(self.xyzs)

        self.method.reset(Config)
