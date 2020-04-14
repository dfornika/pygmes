import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

version = {}
with open("pygmes/version.py") as fp:
    exec(fp.read(), version)
setuptools.setup(
    name="pygmes",
    version=version["__version__"],
    author="Paul Saary",
    author_email="saary@ebi.ac.uk",
    description="Run GeneMark-ES using pretrained models",
    url="https://github.com/openpaul/pygmes",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="",
    py_modules=["api"],
    entry_points={"console_scripts": ["pygmes = pygmes.api:main"]},
    install_requires=["ete3", "pyfaidx>=0.5.8"],
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
