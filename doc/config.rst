Configuration
=============

Configuration is handled with :code:`ade.Config` and can be modified for full
customization of the calculations. By default optimisations are performed at
PBE0-D3BJ/def2-SVP and single points at PBE0-D3BJ/def2-TZVP in ORCA if it is
available.

------------

Calculations
------------

General
*******

For example, to use Gaussian09 as the high level electronic structure method

.. code-block:: python

  >>> import autode as ade
  >>> ade.Config.hcode = 'g09'

To set the number of cores available and the memory per core (in MB), to use a maximum
of 32 GB for the whole calculation

.. code-block:: python

  >>> ade.Config.n_cores = 8
  >>> ade.Config.max_core = 4000

------------

Keywords
********

Calculation parameters (keywords) also can be changed, e.g to use
B3LYP/def2-TZVP single point energies in ORCA

.. code-block:: python

  >>> from autode.wrappers.keywords import SinglePointKeywords
  >>> ade.Config.ORCA.keywords.sp = SinglePointKeywords(['SP', 'B3LYP', 'def2-TZVP'])

Alternatively, to just change the functional

  >>> ade.Config.ORCA.keywords.sp.functional = 'B3LYP'

To add diffuse functions with the ma scheme to the def2-SVP default optimisation
basis set for optimisations

.. code-block:: python

  >>> ade.Config.ORCA.keywords.set_opt_basis_set('ma-def2-SVP')

.. note::
    `set_opt_basis_set` sets the basis set in keywords.grad, keywords.opt_ts
    keywords.opt, keywords.low_opt and keywords.hess.

------------

XTB as a hmethod
****************

To use XTB as the *hmethod* for minima and TS optimisations with the `xtb-gaussian <https://github.com/aspuru-guzik-group/xtb-gaussian>`_ wrapper
and some default options

.. code-block:: python

  >>> ade.Config.G16.keywords.sp = SinglePointKeywords([f"external='xtb-gaussian'"])
  >>> ade.Config.G16.keywords.low_opt = OptKeywords([f"external='xtb-gaussian'", "opt=loose"])
  >>> ade.Config.G16.keywords.opt = OptKeywords([f"external='xtb-gaussian'", "opt"])
  >>> ade.Config.G16.keywords.opt_ts = OptKeywords([f"external='xtb-gaussian'", 'Opt=(TS, CalcFC, NoEigenTest, MaxCycles=100, MaxStep=10, NoTrustUpdate)', "freq"])
  >>> ade.Config.G16.keywords.hess = HessianKeywords([f"external='xtb-gaussian'", 'freq'])
  >>> ade.Config.G16.keywords.grad = GradientKeywords([f"external='xtb-gaussian'", 'Force(NoStep)'])

------------

Other
*****

See the `config file <https://github.com/duartegroup/autodE/blob/master/autode/config.py>`_
to see all the options.

.. note::
    NWChem currently only supports solvents for DFT, other methods must not have
    a solvent.

------------

Logging
-------

To set the logging level to one of {INFO, WARNING, ERROR} set the AUTODE_LOG_LEVEL
environment variable, in bash::

    $ export AUTODE_LOG_LEVEL=INFO

To output the log to a file set e.g. *autode.log*::

    $ export AUTODE_LOG_FILE=autode.log

To log with timestamps and colours::

    $ conda install coloredlogs


