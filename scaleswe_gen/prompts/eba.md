Your goal is to clone, set up environment for a repository within the existing (base) conda environment so that all tests run successfully.
You are now at a GitHub repo at /workspace/{{repository}}.
The base image is Ubuntu 22.04 with Miniconda3 preinstalled you are already inside a conda shell (base environment).
You should install dependencies and configure everything using conda (and pip inside conda if necessary).

The repository is predominantly written in Python. Here are several tips for installing it:
1. A good place to start is to look for a CONTRIBUTING.[md|rst] file, which will often contain instructions on how to install the repository and any dependencies it may have. Occasionally, the README.md file may also contain installation instructions.
2. Usually, a repository may have setup.py or pyproject.toml files which can be used to install the package. pip install -e . is commonly used, although many packages will also require an additional specifier that installs development packages as well (e.g. pip install -e .[dev] or pip install -e .[tests]).
3. To check whether the repository was installed successfully, run tests and see if they pass. You can usually find tests in a tests/ or test/ directory. You can run tests using pytest or unittest, depending on the framework used by the repository.
  **VERY IMPORTANT** YOU MUST APPEND ```--timeout=1800``` TO PYTEST, eg. "pytest ... --timeout=1800".
4. Sometimes, you will need to install additional packages, often listed in a requirements.txt or environment.yml file. Also be mindful of Ubuntu system dependencies that may need to be installed via apt-get (e.g. sudo apt-get install <package>).
5. You MUST fix all errors encountered during testing warnings can be ignored.
6. YOU MUST DO ```pip freeze``` when all test cases pass. In this way I can get all exact version of all packages.
**IMPORTANT: YOU ARE NOT ALLOWED TO CHANGE ANY FILE TO FIX ENVIROMENT PROBLEM. INSTALL CORRECT VERSION PACKAGES TO FIX ENV INSTEAD OF CHANGE ANY FILE.**
Once you are finished with installing the repository, run the submit command to submit your changes for review.
