import logging
import os
import subprocess
import glob
import re
from pyfaidx import Fasta
from random import sample
from collections import defaultdict
from pygmes.diamond import diamond
from pygmes.printlngs import print_lngs


import urllib.request


url = "http://paulsaary.de/gmes/"
def create_dir(d):
    if not os.path.isdir(d):
        try:
            os.makedirs(d)
        except OSError as e:
            logging.warning(f"Could not create dir: {d}\n{e}")



def touch(fname, mode=0o666, dir_fd=None, **kwargs):
    flags = os.O_CREAT | os.O_APPEND
    with os.fdopen(os.open(fname, flags=flags, mode=mode, dir_fd=dir_fd)) as f:
        os.utime(f.fileno() if os.utime in os.supports_fd else fname,
            dir_fd=None if os.supports_fd else dir_fd, **kwargs)

class gmes:
    def __init__(self, fasta, outdir, ncores=1):
        self.fasta = os.path.abspath(fasta)
        self.outdir = os.path.abspath(outdir)
        self.logfile = os.path.join(self.outdir, "pygmes.log")
        self.loggtf = os.path.join(self.outdir, "pygmes_gtf.log")
        # make sure the output folder exists
        create_dir(self.outdir)
        self.ncores = ncores

        self.gtf = os.path.join(self.outdir, "genemark.gtf")
        self.protfaa = os.path.join(self.outdir, "prot_seq.faa")
        self.finalfaa = False
        self.finalgtf = False
        self.modelinfomap = {}

    def selftraining(self):
        failpath = os.path.join(self.outdir, "tried_already")
        if os.path.exists(failpath):
            logging.info("Self-training skipped, as we did this before and it failed")
            return
        if os.path.exists(self.gtf):
            logging.info("GTF file already exists, skipping")
            self.gtf2faa()
            return

        logging.debug("Starting self-training")
        lst = [
            "gmes_petap.pl",
            "--v",
            "--fungus",
            "--ES",
            "--cores",
            str(self.ncores),
            "--min_contig",
            "5000",
            "--sequence",
            self.fasta,
        ]
        try:
            with open(self.logfile, "a") as fout:
                subprocess.run(" ".join(lst), cwd=self.outdir, check=True, shell=True,
                            stdout = fout, stderr = fout)
        except subprocess.CalledProcessError:
            touch(failpath)
            logging.info("GeneMark-ES in self-training mode has failed")
        self.gtf2faa()

    def prediction(self, model):
        self.model = model
        self.modelname = os.path.basename(model).replace(".mod","")
        failpath = os.path.join(self.outdir, "tried_already")
        if os.path.exists(failpath):
            logging.info("Prediction skipped, as we did this before and it failed")
            return
        if os.path.exists(self.gtf):
            logging.info("GTF file already exists, skipping")
            self.gtf2faa()
            return
        logging.debug("Starting prediction")
        lst = [
            "gmes_petap.pl",
            "--v",
            "--predict_with",
            model,
            "--cores",
            str(self.ncores),
            "--sequence",
            self.fasta,
        ]
        try:
            with open(self.logfile, "a") as fout:
                subprocess.run(" ".join(lst), cwd=self.outdir, check=True, shell=True,
                            stdout = fout, stderr = fout)
        except subprocess.CalledProcessError:
            logging.info("GeneMark-ES in prediction mode has failed")
            touch(failpath)
        self.gtf2faa()

    def gtf2faa(self):
        lst = ["get_sequence_from_GTF.pl", "genemark.gtf", self.fasta]
        if not os.path.exists(self.gtf):
            logging.warning("There is no GTF file")
            return
        if os.path.exists(self.protfaa):
            logging.info("Protein file already exists, skipping")
            return
        try:
            with open(self.loggtf, "a") as fout:
                subprocess.run(" ".join(lst), cwd=self.outdir, check=True, shell=True,
                            stdout = fout, stderr = fout)
        except subprocess.CalledProcessError:
            logging.warning("could not get proteins from gtf")
    
    def gtf2bed(self, gtf, outfile):
        """
        given a faa file and a gtf(genemark-es format)
        we will be able to create a bed file, which can be used 
        with eukcc
        """
        nre = re.compile(r'gene_id "([0-9]+_g)\";')
        def beddict():
            return({"chrom": None, "r": [], "strand": None})
        beds = defaultdict(beddict)

        with open(gtf) as f:
            for line in f:
                # skip comment lines
                if line.startswith("#"):
                    continue

                l = line.split("\t")
                chrom = l[0].strip()
                start = int(l[3])
                stop = int(l[4])
                strand = l[6]

                # regex match
                m = (nre.findall(l[8]))
                if m is not None:
                    name = m[0]
                else:
                    continue
    
                # save all in the dictonary
                beds[name]["chrom"] = l[0]
                beds[name]["r"].append(int(l[3]))
                beds[name]["r"].append(int(l[4]))
                beds[name]["strand"] = l[6]

        # write to file
        with open(outfile, "w") as f:
            for name, v in beds.items():
                vals = "\t".join([v["chrom"], str(min(v["r"])), str(max(v["r"])), v['strand'], name])
                f.write("{}\n".format(vals))

        

    def check_success(self):
        if not os.path.exists(self.gtf):
            return False
        if not os.path.exists(self.protfaa):
            return False

        # now more in detail
        # check if proteins are empty maybe
        with open(self.protfaa) as fa:
            j = 1
            for line in fa:
                if j == 0:
                    if line.strip() == "":
                        return False
                    else:
                        return True
                j = j - 1

    def run_complete(self, models, diamonddb):
        self.selftraining()
        if self.check_success():
            logging.info("Ran GeneMark-ES successfully")
            self.finalfaa = self.protfaa
            self.finalgtf = self.gtf
        else:
            logging.info("Using pre-trained models")
            self.fetchinfomap()
            self.premodel(models)
            if self.bestpremodel:
                self.bestpremodel.estimate_tax(diamonddb)
                self.premodeltax = self.bestpremodel.tax
                # print linegae of model compared to the infered tax
                print_lngs(self.modelinfomap[self.bestpremodel.modelname],
                           self.premodeltax)
                localmodals = self.infer_model(self.premodeltax)
                self.premodel(localmodals, stage=2)
                self.bestpremodel.estimate_tax(diamonddb)
                self.premodeltax = self.bestpremodel.tax
                # print linegae of model compared to the infered tax
                print_lngs(self.modelinfomap[self.bestpremodel.modelname],
                           self.premodeltax)
                self.finalfaa = self.bestpremodel.protfaa
                self.finalgtf = self.bestpremodel.gtf
            # self.prediction()

    def estimate_tax(self, db):
        ddir = os.path.join(self.outdir, "diamond")
        create_dir(ddir)
        d = diamond(self.protfaa, ddir, db, sample=200, ncores = self.ncores)
        self.tax = d.lineage

    def premodel(self, models, stage=1):
        logging.debug("Running the pre Model stage %d" % stage)
        logging.debug("Using model directory: %s", models)
        self.bestpremodel = False
        modelfiles = glob.glob(os.path.join(models, "*.mod"))
        subgmes = []
        for model in modelfiles:
            logging.debug("Using model %s" % os.path.basename(model))
            name = os.path.basename(model)
            odir = os.path.join(self.outdir, "{}_premodels".format(stage), name)
            g = gmes(self.fasta, odir, ncores = self.ncores)
            g.prediction(model)
            if g.check_success():
                subgmes.append(g)

        if len(subgmes) == 0:
            logging.warning("Could not predict any proteins in this file")
        else:
            aminoacidcount = []
            for g in subgmes:
                fa = Fasta(g.protfaa)
                i = 0
                for seq in fa:
                    i += len(seq)
                aminoacidcount.append(i)
            # set the best model as the model leading to the most amino acids
            idx = aminoacidcount.index(max(aminoacidcount))
            self.bestpremodel = subgmes[idx]
            logging.info("Best model set as: %s" % os.path.basename(self.bestpremodel.model))

    def fetchinfomap(self):
        """
        function to make sure the information of all models
        is known to the class
        """
        if len(self.modelinfomap) == 0:
            info = self.fetch_info("{}info.csv".format(url))
            for line in info.split("\n"):
                l = line.split(",")
                if len(l) == 3:
                    self.modelinfomap[l[0]] = l[2].split("-")

    def infer_model(self, tax, n=3):
        """
        given we infered a lineage or we know a lineage
        we can try to fetch a model from the number of
        precomputed models that already exists
        for this we choose the model that shares the most
        taxonomic element with the predicted lineage
        If multiple modles have similar fit, we just again chose the best one
        """
        self.fetchinfomap()

        candidates = self.score_models(self.modelinfomap, tax)

        if len(candidates) > n:
            candidates = sample(candidates, n)
        # for each candidate, try to download the model into a file
        modeldir = os.path.join(self.outdir, "models")
        create_dir(modeldir)
        for model in candidates:
            self.fetch_model(modeldir, url, model)

        return modeldir

    def fetch_model(self, folder, url, name):
        url = "{}/models/{}.mod".format(url, name)
        modelfile = os.path.join(folder, "{}.mod".format(name))
        response = urllib.request.urlopen(url)
        data = response.read()  # a `bytes` object
        content = data.decode(
            "utf-8"
        )  # a `str`; this step can't be used if data is binary
        with open(modelfile, "w") as mod:
            mod.writelines(content)

    def fetch_info(self, url):
        response = urllib.request.urlopen(url)
        data = response.read()  # a `bytes` object
        infocsv = data.decode(
            "utf-8"
        )  # a `str`; this step can't be used if data is binary
        return infocsv

    def score_models(self, infomap, lng):
        scores = defaultdict(int)

        for model, mlng in infomap.items():
            for a, b in zip(lng, mlng):
                if int(a) == int(b):
                    scores[model] += 1
        # get all models with the highest score
        maxscore = max([v for k, v in scores.items()])
        candidates = []
        for m, s in scores.items():
            if s == maxscore:
                candidates.append(m)
        return candidates
