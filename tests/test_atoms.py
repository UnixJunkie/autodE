import numpy as np
import pytest
from autode import atoms
from autode.atoms import Atom, DummyAtom, Atoms
from autode.values import Angle, Coordinate, Mass


def test_valency():

    assert Atom('C').maximal_valance == 4

    # Default to 6 if the atom does not have a hard-coded maximum valency
    assert Atom('Sc').maximal_valance == 6


def test_vdw_radius():

    assert 0.9 < Atom('H').vdw_radius < 1.2

    # Defaults to ~2.5 Å if the van der Waals radius is unknown
    assert 2 < Atom('Og').vdw_radius < 3


def test_is_pi():

    assert Atom('C').is_pi(valency=3)
    assert not Atom('H').is_pi(valency=1)

    assert not Atom('C').is_pi(valency=4)
    assert not Atom('Sc').is_pi(valency=9)


def test_atoms():

    empty_atoms = Atoms()
    assert 'atoms' in repr(empty_atoms).lower()
    assert not empty_atoms.are_linear()
    assert len(empty_atoms + None) == 0

    # Undefined COM with no atoms
    with pytest.raises(ValueError):
        _ = empty_atoms.com

    h_atoms = Atoms([Atom('H'), Atom('H', x=1.0)])
    assert isinstance(h_atoms.com, Coordinate)
    assert np.allclose(h_atoms.com, np.array([0.5, 0.0, 0.0]))

    assert h_atoms.vector(0, 1) == np.array([1.0, 0.0, 0.0])

    # Moment of inertia
    assert np.sum(np.diag(h_atoms.moi)) > 0.0
    assert 1.9 < np.sum(np.diag(h_atoms.moi)) < 2.1

    h_atoms_far = Atoms([Atom('H'), Atom('H', x=10.0)])
    assert np.sum(h_atoms_far.moi) > np.sum(h_atoms.moi)

    assert np.isclose(np.linalg.norm(h_atoms_far.nvector(0, 1)), 1.0)

    # COM is weighted by mass, so the x-coordinate
    ch_atoms = Atoms([Atom('H'), Atom('C', x=1.0)])

    assert 0.5 < ch_atoms.com.x < 1.0
    assert ch_atoms.com.y == 0.0
    assert ch_atoms.com.z == 0.0

    h_and_dummy_atoms = Atoms([Atom('H'), DummyAtom(0, 0, 0)])
    assert len(h_and_dummy_atoms) == 2
    h_and_dummy_atoms.remove_dummy()
    assert len(h_and_dummy_atoms) == 1


def test_atom_collection_base():

    h2 = atoms.AtomCollection()
    assert h2.n_atoms == 0
    assert np.isclose(h2.weight, 0.0)    # 0 weight for 0 atoms
    assert h2.coordinates is None
    assert h2.moi is None and h2.com is None

    # Cannot set coordinates without atoms
    with pytest.raises(ValueError):
        h2.coordinates = np.array([1.0, 1.0, 1.0])

    h2.atoms = [Atom('H', 0.0, 0.0, 0.0), Atom('H')]
    assert h2.n_atoms == 2

    assert h2.weight.to('amu') == 2*atoms.atomic_weights['H']
    assert h2.mass.to('amu') == 2*atoms.atomic_weights['H']

    # Should be able to set coordinate from a flat array (row major)
    h2.coordinates = np.zeros(shape=(6,))
    assert h2.coordinates[0] is not None
    assert h2.n_atoms == 2

    assert np.isclose(h2.distance(0, 1), 0.0, atol=1E-5)

    coord = h2.coordinates[0]
    coord += 1.0

    # Shift of coordinates should not be in place
    assert not np.allclose(h2.coordinates[0], coord)

    # Cannot set coordinates with anything but a 3xn_atoms flat array, or
    # 2-dimensional array (matrix)
    with pytest.raises(AssertionError):
        h2.coordinates = np.array([])

    with pytest.raises(AssertionError):
        h2.coordinates = np.array([1.0, 0.1])

    with pytest.raises(AssertionError):
        h2.coordinates = np.array([[[1.0], [1.0]]])

    with pytest.raises(ValueError):
        h2.distance(-1, 0)

    with pytest.raises(ValueError):
        h2.distance(0, 2)


def test_atom_collection_angles():

    h2o = atoms.AtomCollection()
    h2o.atoms = [Atom('H', x=-1.0),
                 Atom('O'),
                 Atom('H', x=1.0)]

    assert np.isclose(h2o.mass.to('amu'), 18, atol=0.2)

    # Should default to more human readable degree units
    assert np.isclose(h2o.angle(0, 1, 2).to('deg'), 180)
    assert np.isclose(h2o.angle(0, 1, 2).to('degrees'), 180)

    # No -1 atom
    with pytest.raises(ValueError):
        _ = h2o.angle(-1, 0, 1)

    # Angle is not defined when one vector is the zero vector
    with pytest.raises(ValueError):
        _ = h2o.angle(0, 0, 1)

    # Angles default to radians
    assert np.isclose(np.abs(h2o.angle(0, 1, 2)), np.pi)

    with pytest.raises(TypeError):
        _ = h2o.angle(0, 1, 2).to('not a unit')

    assert isinstance(h2o.angle(0, 1, 2).copy(), Angle)

    h2o.atoms[1].coord = np.array([-0.8239, -0.5450, 0.0000])
    h2o.atoms[2].coord = np.array([0.8272, -0.5443, 0.0000])

    assert 90 < h2o.angle(0, 1, 2).to('deg') < 120


def test_atom_collection_dihedral():

    h2o2 = atoms.AtomCollection()
    h2o2.atoms = [Atom('O', -0.85156, -0.20464,  0.31961),
                  Atom('O',  0.41972,  0.06319,  0.10395),
                  Atom('H', -1.31500,  0.08239, -0.50846),
                  Atom('H',  0.58605,  0.91107,  0.59006)]

    assert np.isclose(h2o2.dihedral(2, 0, 1, 3).to('deg'),
                      100.8,
                      atol=1.0)

    # Undefined dihedral with a zero vector between two atoms
    with pytest.raises(ValueError):
        h2o2.atoms[0].coord = np.zeros(3)
        h2o2.atoms[1].coord = np.zeros(3)

        _ = h2o2.dihedral(2, 0, 1, 3)

    # and a dihedral with atoms not present in the molecule
    with pytest.raises(ValueError):
        _ = h2o2.dihedral(2, 0, 1, 10)


def test_atom_h():

    h = Atom(atomic_symbol='H', x=0.0, y=0.0, z=0.0)
    assert h.label == 'H'
    assert h.atomic_number == 1
    assert h.atomic_symbol == 'H'
    assert not h.is_metal
    assert h.tm_row is None
    assert h.group == 1
    assert h.period == 1

    assert len(h.coord) == 3
    assert h.coord[0] == 0
    assert h.coord[1] == 0
    assert h.coord[2] == 0

    # Translate the H atom by 1 A in the z direction
    h.translate(vec=np.array([0.0, 0.0, 1.0]))
    assert np.linalg.norm(h.coord - np.array([0.0, 0.0, 1.0])) < 1E-6

    with pytest.raises(ValueError):
        h.translate(some_unkown_arg=5)

    # Rotate the atom 180° (pi radians) in the x axis
    h.rotate(axis=np.array([1.0, 0.0, 0.0]), theta=np.pi)
    assert np.linalg.norm(h.coord - np.array([0.0, 0.0, -1.0])) < 1E-6

    # Perform a rotation about a different origin e.g. (1, 0, -1)
    h.rotate(axis=np.array([0.0, 0.0, 1.0]),
             theta=np.pi,
             origin=np.array([1.0, 0.0, -1.0]))
    assert np.linalg.norm(h.coord - np.array([2.0, 0.0, -1.0])) < 1E-6

    # Ensure that the atoms has a string representation
    assert len(str(h)) > 0


def test_atom_other():
    assert Atom('C').atomic_number == 6
    assert Atom('C').period == 2
    assert Atom('C').group == 14
    assert 11.9 < Atom('C').weight.to('amu') < 12.1

    dummy = atoms.DummyAtom(0.0, 0.0, 0.0)
    assert dummy.atomic_number == 0
    assert dummy.period == 0
    assert dummy.group == 0
    assert dummy.mass == dummy.weight == 0.0

    fe = Atom(atomic_symbol='Fe')
    assert fe.tm_row == 1

    # Should have a mass, even if it's estimated for all elements
    for element in atoms.elements:
        atom = Atom(element)
        assert atom.weight is not None


def test_atom_coord_setting():

    atom = Atom('H', 0.0, 0.0, 0.0)

    with pytest.raises(ValueError):
        atom.coord = None

    with pytest.raises(ValueError):
        atom.coord = [1.0, 10]

    with pytest.raises(ValueError):
        atom.coord = 1.0, 1.0

    atom.coord = np.array([1.0, 0.0, 0.0])
    assert np.allclose(atom.coord.to('nm'), np.array([0.1, 0.0, 0.0]))


def test_periodic_table():

    with pytest.raises(ValueError):
        _ = atoms.PeriodicTable.period(n=0)   # Periods are indexed from 1
        _ = atoms.PeriodicTable.period(n=8)   # and don't exceed 8

        _ = atoms.PeriodicTable.period(n=19)   # Groups don't exceed 18

    period2 = atoms.PeriodicTable.period(n=2)
    assert len(period2) == 8
    assert period2[0] == 'Li'

    assert len(atoms.PeriodicTable.period(n=1)) == 2
    assert len(atoms.PeriodicTable.period(n=3)) == 8
    assert len(atoms.PeriodicTable.period(n=4)) == 18

    group13 = atoms.PeriodicTable.group(n=13)
    assert 'B' in group13

    with pytest.raises(Exception):
        _ = atoms.PeriodicTable.group(0)   # No group 0
        _ = atoms.PeriodicTable.group(19)  # or 19

    with pytest.raises(IndexError):
        _ = atoms.PeriodicTable.element(0, 0)
        _ = atoms.PeriodicTable.element(0, 3)

    with pytest.raises(Exception):
        _ = atoms.PeriodicTable.transition_metals(row=0)
        _ = atoms.PeriodicTable.transition_metals(row=10)

    assert 'Fe' in atoms.PeriodicTable.transition_metals(row=1)

    assert atoms.PeriodicTable.element(2, 13) == 'B'


def test_doc_examples():

    assert Atom('C').atomic_number == 6

    assert Atom('Zn').atomic_symbol == 'Zn'

    assert Atom('H').coord == Coordinate(0.0, 0.0, 0.0, units='Å')
    assert np.isclose(Atom('H', x=1.0).coord.x, 1.0)
    assert np.allclose(Atom('H', x=1.0).coord.to('a0'),
                       Coordinate(1.889, 0.0, 0.0, units='bohr'),
                       atol=1E-3)

    assert not Atom('C').is_metal
    assert Atom('Zn').is_metal

    assert Atom('C').group == 14

    assert Atom('C').period == 2

    assert Atom('C').weight == Mass(12.0107, units='amu')
    assert Atom('C').weight == Atom('C').mass

    assert Atom('H').mass.to('me') == Mass(1837.36222, units='m_e')

    atom = Atom('H')
    atom.translate(1.0, 0.0, 0.0)
    assert atom.coord == Coordinate(1.0, 0.0, 0.0, units='Å')

    atom = Atom('H')
    atom.translate(np.ones(3))
    assert atom.coord == Coordinate(1.0, 1.0, 1.0, units='Å')
    atom.translate(vec=-atom.coord)
    assert atom.coord == Coordinate(0.0, 0.0, 0.0, units='Å')

    atom = Atom('H', x=1.0)
    atom.rotate(axis=[0.0, 0.0, 1.0], theta=3.14)
    assert np.allclose(atom.coord,
                       Coordinate(-1, 0., 0., units='Å'),
                       atol=1E-2)

    from autode.values import Angle
    atom  = Atom('H', x=1.0)
    atom.rotate(axis=[0.0, 0.0, 1.0], theta=Angle(180, units='deg'))
    assert np.allclose(atom.coord,
                       Coordinate(-1, 0., 0., units='Å'),
                       atol=1E-5)
