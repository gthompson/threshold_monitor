# To build Python environment (on Ubuntu 22.04 VM, but should work for Linux and Mac systems):
mkdir -p ~/miniconda3
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
rm -rf ~/miniconda3/miniconda.sh
~/miniconda/bin/conda init bash
. ~/.bashrc
conda config --add channels conda-forge
conda create -n obspy python=3.10 obspy cartopy pytest pytest-json pytest-json-report geographiclib
conda activate obspy
conda install pandas 
conda install anaconda::pyyaml
conda install filelock
# GT: 2024/08/20

