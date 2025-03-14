import numpy as np
import os
import autode.wrappers.keywords as kws
from autode.constants import Constants
from autode.utils import run_external
from autode.wrappers.base import ElectronicStructureMethod
from autode.atoms import Atom
from autode.input_output import xyz_file_to_atoms
from autode.config import Config
from autode.utils import work_in_tmp_dir
from autode.log import logger
from autode.exceptions import (UnsuppportedCalculationInput,
                               CouldNotGetProperty,
                               NoCalculationOutput,
                               XYZfileWrongFormat,
                               AtomsNotFound)

vdw_gaussian_solvent_dict = {'water': 'Water', 'acetone': 'Acetone', 'acetonitrile': 'Acetonitrile', 'benzene': 'Benzene',
                             'carbon tetrachloride': 'CCl4', 'dichloromethane': 'CH2Cl2', 'chloroform': 'Chloroform', 'cyclohexane': 'Cyclohexane',
                             'n,n-dimethylformamide': 'DMF', 'dimethylsulfoxide': 'DMSO', 'ethanol': 'Ethanol', 'n-hexane': 'Hexane',
                             'methanol': 'Methanol', '1-octanol': 'Octanol', 'pyridine': 'Pyridine', 'tetrahydrofuran': 'THF', 'toluene': 'Toluene'}


def use_vdw_gaussian_solvent(keywords, implicit_solv_type):
    """
    Determine if the calculation should use the gaussian charge scheme which
    generally affords better convergence for optimiations in implicit solvent

    Arguments:
        keywords (autode.wrappers.keywords.Keywords):
        implicit_solv_type (str):

    Returns:
        (bool):
    """
    if implicit_solv_type.lower() != 'cpcm':
        return False

    if any('freq' in kw.lower() or 'optts' in kw.lower() for kw in keywords):
        logger.warning('Cannot do analytical frequencies with gaussian charge '
                       'scheme - switching off')
        return False

    return True


def add_solvent_keyword(calc_input, keywords, implicit_solv_type):
    """Add a keyword to the input file based on the solvent"""

    if implicit_solv_type.lower() not in ['smd', 'cpcm']:
        raise UnsuppportedCalculationInput

    # Use CPCM solvation
    if (use_vdw_gaussian_solvent(keywords, implicit_solv_type)
            and calc_input.solvent not in vdw_gaussian_solvent_dict.keys()):

        err = (f'CPCM solvent with gaussian charge not avalible for '
               f'{calc_input.solvent}. Available solvents are '
               f'{vdw_gaussian_solvent_dict.keys()}')

        raise UnsuppportedCalculationInput(message=err)

    keywords.append(f'CPCM({vdw_gaussian_solvent_dict[calc_input.solvent]})')
    return


def get_keywords(calc_input, molecule, implicit_solv_type):
    """Modify the keywords for this calculation with the solvent + fix for
    single atom optimisation calls"""

    new_keywords = []

    for keyword in calc_input.keywords.copy():
        if 'opt' in keyword.lower() and molecule.n_atoms == 1:
            logger.warning('Can\'t optimise a single atom')
            continue

        if isinstance(keyword, kws.ECP) and keyword.orca is None:
            # Use the default specification for applying ECPs
            continue

        if isinstance(keyword, kws.MaxOptCycles):
            continue  # Set in print_num_optimisation_steps

        if isinstance(keyword, kws.Keyword):
            new_keywords.append(keyword.orca)

        else:
            new_keywords.append(str(keyword))

    if calc_input.solvent is not None:
        add_solvent_keyword(calc_input, new_keywords, implicit_solv_type)

    # Sort the keywords with all the items with newlines at the end, so
    # the first keyword line is a single contiguous line
    return sorted(new_keywords, key=lambda kw: 1 if '\n' in kw else 0)


def print_solvent(inp_file, calc_input, keywords, implicit_solv_type):
    """Add the solvent block to the input file"""
    if calc_input.solvent is None:
        return

    if implicit_solv_type.lower() == 'smd':
        print(f'%cpcm\n'
              f'smd true\n'
              f'SMDsolvent \"{calc_input.solvent}\"\n'
              f'end', file=inp_file)

    if use_vdw_gaussian_solvent(keywords, implicit_solv_type):
        print('%cpcm\n'
              'surfacetype vdw_gaussian\n'
              'end', file=inp_file)
    return


def print_added_internals(inp_file, calc_input):
    """Print the added internal coordinates"""

    if calc_input.added_internals is None:
        return

    for (i, j) in calc_input.added_internals:
        print('%geom\n'
              'modify_internal\n'
              '{ B', i, j, 'A } end\n'
              'end', file=inp_file)
    return


def print_distance_constraints(inp_file, molecule):
    """Print the distance constraints to the input file"""
    if molecule.constraints.distance is None:
        return

    print('%geom Constraints', file=inp_file)
    for (i, j), dist in molecule.constraints.distance.items():
        print('{ B', i, j, dist, 'C }', file=inp_file)
    print('    end\nend', file=inp_file)

    return


def print_cartesian_constraints(inp_file, molecule):
    """Print the Cartesian constraints to the input file"""

    if molecule.constraints.cartesian is None:
        return

    print('%geom Constraints', file=inp_file)
    for i in molecule.constraints.cartesian:
        print('{ C', i, 'C }', file=inp_file)
    print('    end\nend', file=inp_file)

    return


def print_num_optimisation_steps(inp_file, molecule, calc_input):
    """If there are relatively few atoms increase the number of opt steps"""

    if not isinstance(calc_input.keywords, kws.OptKeywords):
        return   # Not an optimisation so no need to increase steps

    if calc_input.keywords.max_opt_cycles is not None:
        print(f'%geom MaxIter {int(calc_input.keywords.max_opt_cycles)} end',
              file=inp_file)
        return

    if molecule.n_atoms > 33:
        return  # Use default behaviour

    block = calc_input.other_block
    if block is None or 'maxit' not in block.lower():
        print('%geom MaxIter 100 end', file=inp_file)

    return


def print_point_charges(inp_file, calc_input):
    """Print a point charge file and add the name to the input file"""

    if calc_input.point_charges is None:
        return

    filename = calc_input.filename.replace('.inp', '.pc')
    with open(filename, 'w') as pc_file:
        print(len(calc_input.point_charges), file=pc_file)
        for pc in calc_input.point_charges:
            x, y, z = pc.coord
            print(f'{pc.charge:^12.8f} {x:^12.8f} {y:^12.8f} {z:^12.8f}',
                  file=pc_file)

    calc_input.additional_filenames.append(filename)

    print(f'% pointcharges "{filename}"', file=inp_file)
    return


def print_default_params(inp_file):
    """Print some useful default parameters to the input file"""

    print('%output \nxyzfile=True \nend ',
          '%scf \nmaxiter 250 \nend',
          '%output\nPrint[P_Hirshfeld] = 1\nend',
          '% maxcore', Config.max_core, sep='\n', file=inp_file)
    return


def print_coordinates(inp_file, molecule):
    """Print the coordinates to the input file in the correct format"""

    print('*xyz', molecule.charge, molecule.mult, file=inp_file)
    for atom in molecule.atoms:
        x, y, z = atom.coord
        print(f'{atom.label:<3} {x:^12.8f} {y:^12.8f} {z:^12.8f}',
              file=inp_file)
    print('*', file=inp_file)

    return


class ORCA(ElectronicStructureMethod):

    def generate_input(self, calc, molecule):

        keywords = get_keywords(calc.input, molecule,
                                self.implicit_solvation_type)

        with open(calc.input.filename, 'w') as inp_file:
            print('!', *keywords, file=inp_file)

            print_solvent(inp_file, calc.input, keywords,
                          self.implicit_solvation_type)
            print_added_internals(inp_file, calc.input)
            print_distance_constraints(inp_file, molecule)
            print_cartesian_constraints(inp_file, molecule)
            print_num_optimisation_steps(inp_file, molecule, calc.input)
            print_point_charges(inp_file, calc.input)
            print_default_params(inp_file)
            if Config.ORCA.other_input_block is not None:
                print(Config.ORCA.other_input_block, file=inp_file)

            if calc.input.other_block is not None:
                print(calc.input.other_block, file=inp_file)

            if calc.n_cores > 1:
                print(f'%pal nprocs {calc.n_cores}\nend', file=inp_file)

            print_coordinates(inp_file, molecule)

        return None

    def get_input_filename(self, calc):
        return f'{calc.name}.inp'

    def get_output_filename(self, calc):
        return f'{calc.name}.out'

    def get_version(self, calc):
        """Get the version of ORCA used to execute this calculation"""

        for line in calc.output.file_lines:
            if 'Program Version' in line and len(line.split()) >= 3:
                return line.split()[2]

        logger.warning('Could not find the ORCA version number')
        return '???'

    def execute(self, calc):

        @work_in_tmp_dir(filenames_to_copy=calc.input.filenames,
                         kept_file_exts=('.out', '.hess', '.xyz', '.inp', '.pc'))
        def execute_orca():
            run_external(params=[calc.method.path, calc.input.filename],
                         output_filename=calc.output.filename)

        execute_orca()
        return None

    def calculation_terminated_normally(self, calc):

        termination_strings = ['ORCA TERMINATED NORMALLY',
                               'The optimization did not converge']

        for n_line, line in enumerate(reversed(calc.output.file_lines)):

            if any(substring in line for substring in termination_strings):
                logger.info('orca terminated normally')
                return True

            if n_line > 30:
                # The above lines are pretty close to the end of the file –
                # so skip parsing it all
                return False

        return False

    def get_energy(self, calc):

        for line in reversed(calc.output.file_lines):
            if 'FINAL SINGLE POINT ENERGY' in line:
                return float(line.split()[4])

        raise CouldNotGetProperty(name='energy')

    def optimisation_converged(self, calc):

        for line in reversed(calc.output.file_lines):
            if 'THE OPTIMIZATION HAS CONVERGED' in line:
                return True

        return False

    def optimisation_nearly_converged(self, calc):
        geom_conv_block = False

        for line in reversed(calc.output.file_lines):
            if geom_conv_block and 'Geometry convergence' in line:
                geom_conv_block = False
            if 'The optimization has not yet converged' in line:
                geom_conv_block = True
            if geom_conv_block and len(line.split()) == 5:
                if line.split()[-1] == 'YES':
                    return True

        return False

    def get_final_atoms(self, calc):
        """
        Get the final set of atoms from an ORCA output file

        Arguments:
            calc (autode.calculation.Calculation):

        Returns:
            (list(autode.atoms.Atom)):

        Raises:
            (autode.exceptions.NoCalculationOutput
            | autode.exceptions.AtomsNotFound)
        """

        fn_ext = '.hess' if calc.output.filename.endswith('.hess') else '.out'

        # First try the .xyz file generated
        xyz_file_name = calc.output.filename.replace(fn_ext, '.xyz')
        if os.path.exists(xyz_file_name):

            try:
                return xyz_file_to_atoms(xyz_file_name)

            except XYZfileWrongFormat:
                raise AtomsNotFound(f'Failed to parse {xyz_file_name}')

        # Then the Hessian file
        hess_file_name = calc.output.filename.replace(fn_ext, '.hess')
        if os.path.exists(hess_file_name):
            hess_file_lines = open(hess_file_name, 'r').readlines()

            atoms = []
            for i, line in enumerate(hess_file_lines):
                if '$atoms' not in line:
                    continue

                for aline in hess_file_lines[i+2:i+2+calc.molecule.n_atoms]:
                    label, _, x, y, z = aline.split()
                    atom = Atom(label, x, y, z)
                    # Coordinates in the Hessian file are all atomic units
                    atom.coord *= Constants.a0_to_ang

                    atoms.append(atom)

                return atoms

        # and finally the potentially long .out file
        if os.path.exists(calc.output.filename) and fn_ext == '.out':
            atoms = []

            # There could be many sets in the file, so take the last
            for i, line in enumerate(calc.output.file_lines):
                if 'CARTESIAN COORDINATES (ANGSTROEM)' not in line:
                    continue

                atoms, n_atoms = [], calc.molecule.n_atoms
                for oline in calc.output.file_lines[i+2:i+2+n_atoms]:
                    label, x, y, z = oline.split()
                    atoms.append(Atom(label, x, y, z))

            return atoms

        raise NoCalculationOutput('Failed to find any ORCA output files')

    def get_atomic_charges(self, calc):
        """
        e.g.

       .HIRSHFELD ANALYSIS
        ------------------

        Total integrated alpha density =     12.997461186
        Total integrated beta density  =     12.997461186

          ATOM     CHARGE      SPIN
           0 C   -0.006954    0.000000
           . .      .            .
        """
        charges = []

        for i, line in enumerate(calc.output.file_lines):
            if 'HIRSHFELD ANALYSIS' in line:
                charges = []
                first, last = i+7, i+7+calc.molecule.n_atoms
                for charge_line in calc.output.file_lines[first:last]:
                    charges.append(float(charge_line.split()[-1]))

        return charges

    def get_gradients(self, calc):
        """
        e.g.

        #------------------
        CARTESIAN GRADIENT                                            <- i
        #------------------

           1   C   :   -0.011390275   -0.000447412    0.000552736    <- j
        """
        gradients = []

        for i, line in enumerate(calc.output.file_lines):
            if 'CARTESIAN GRADIENT' in line or 'The final MP2 gradient' in line:
                gradients = []
                if 'CARTESIAN GRADIENT' in line:
                    first, last = i + 3, i + 3 + calc.molecule.n_atoms
                if 'The final MP2 gradient' in line:
                    first, last = i + 1, i + 1 + calc.molecule.n_atoms
                if 'CARTESIAN GRADIENT (NUMERICAL)' in line:
                    first, last = i + 2, i + 2 + calc.molecule.n_atoms

                for grad_line in calc.output.file_lines[first:last]:

                    if len(grad_line.split()) <= 3:
                        continue

                    dadx, dady, dadz = grad_line.split()[-3:]
                    gradients.append([float(dadx), float(dady), float(dadz)])

        # Convert from Ha a0^-1 to Ha A-1
        return np.array(gradients) / Constants.a0_to_ang

    @staticmethod
    def _start_line_hessian(calc, file_lines):
        """
        Find the line where the Hessian starts in an ORCA Hessian file
        e.g. H2O.hess

        Arguments:
            calc (autode.calculation.Calculation):
            file_lines (list(str)):

        Returns:
            (int):

        Raises:
            (autode.exceptions.CouldNotGetProperty | AssertionError):
        """

        for i, line in enumerate(file_lines):

            if '$hessian' not in line:
                continue

            # Ensure the number of atoms is present, and is the number expected
            n_atoms = int(file_lines[i + 1].split()[0]) // 3
            assert n_atoms == calc.molecule.n_atoms
            return i + 3

        raise CouldNotGetProperty(f'No Hessian found in the Hessian file')

    def get_hessian(self, calc):
        """Grab the Hessian from the output .hess file

        e.g.::

            $hessian
            9
                        0         1
                               2          3            4
            0      6.48E-01   4.376E-03   2.411E-09  -3.266E-01  -2.5184E-01
            .         .          .           .           .           .
        """

        hess_filename = calc.output.filename

        if calc.output.filename.endswith('.out'):
            hess_filename = calc.output.filename.replace('.out', '.hess')

        if not os.path.exists(hess_filename):
            raise CouldNotGetProperty('Could not find Hessian file')

        file_lines = open(hess_filename, 'r', encoding="utf-8").readlines()

        hessian_blocks = []
        start_line = self._start_line_hessian(calc, file_lines)

        for j, h_line in enumerate(file_lines[start_line:]):

            if len(h_line.split()) == 0:
                # Assume we're at the end of the Hessian
                break

            # Skip blank lines in the file, marked by one or more fewer items
            # than the previous
            if len(h_line.split()) < len(file_lines[start_line+j-1].split()):
                continue

            # First item is the coordinate number, thus append all others
            hessian_blocks.append([float(v) for v in h_line.split()[1:]])

        n_atoms = calc.molecule.n_atoms
        hessian = [block for block in hessian_blocks[:3*n_atoms]]

        for i, block in enumerate(hessian_blocks[3*n_atoms:]):
            hessian[i % (3 * n_atoms)] += block

        # Hessians printed in Ha/a0^2, so convert to base Ha/Å^2
        return np.array(hessian, dtype='f8') / Constants.a0_to_ang**2

    def __init__(self):
        super().__init__('orca',
                         path=Config.ORCA.path,
                         keywords_set=Config.ORCA.keywords,
                         implicit_solvation_type=Config.ORCA.implicit_solvation_type,
                         doi_list=['10.1002/wcms.81', '10.1002/wcms.1327'])


orca = ORCA()
