"""
Acapella extraction with a CNN

Typical usage:
    python acapellabot.py song.wav
    => Extracts acapella from <song.wav>
       to <song (Acapella Attempt).wav> using default weights

    python acapellabot.py --data input_folder \
            --batch 32 --weights new_model_iteration.h5
    => Trains a new model based on song/acapella pairs
       in the folder <input_folder>
       and saves weights to <new_model_iteration.h5> once complete.
       See data.py for data specifications.
"""

import random
import string
import os
import sys

import numpy as np
from keras.utils import plot_model

import console
import conversion

from data import Data
from config import config
from metrics import Metrics
from checkpointer import Checkpointer
from modeler import Modeler
from loss import Loss
from chopper import Chopper
from normalizer import Normalizer


class AcapellaBot:
    def __init__(self, config):
        self.config = config
        metrics = Metrics().get()
        m = Modeler().get()
        loss = Loss().get()
        console.log("Model has", m.count_params(), "params")
        m.compile(loss=loss, optimizer='adam', metrics=metrics)
        m.summary(line_length=150)
        plot_model(m, to_file='model.png', show_shapes=True)
        self.model = m
        # need to know so that we can avoid rounding errors with spectrogram
        # this should represent how much the input gets downscaled
        # in the middle of the network
        self.peakDownscaleFactor = 4

    def train(self, data, epochs, batch=8, start_epoch=0):
        xTrain, yTrain = data.train()
        xValid, yValid = data.valid()
        self.xValid, self.yValid = xValid, yValid
        checkpointer = Checkpointer(self)
        checkpoints = checkpointer.get()
        while epochs > 0:
            end_epoch = start_epoch + epochs
            console.log("Training for", epochs, "epochs on",
                        len(xTrain), "examples")
            self.model.fit(xTrain, yTrain, batch_size=batch,
                           initial_epoch=start_epoch, epochs=end_epoch,
                           validation_data=(xValid, yValid),
                           callbacks=checkpoints)
            console.notify(str(epochs) + " Epochs Complete!",
                           "Training on", data.inPath, "with size", batch)

            start_epoch += epochs
            if self.config.quit:
                break
            else:
                while True:
                    try:
                        epochs = int(
                            input("How many more epochs should we train for?"))
                        break
                    except ValueError:
                        console.warn(
                            "Oops, number parse failed. Try again, I guess?")
                if epochs > 0:
                    save = input("Should we save intermediate weights [y/n]? ")
                    if not save.lower().startswith("n"):
                        weightPath = ''.join(random.choice(string.digits)
                                             for _ in range(16)) + ".h5"
                        console.log("Saving intermediate weights to",
                                    weightPath)
                        self.saveWeights(weightPath)

    def saveWeights(self, path):
        self.model.save_weights(path, overwrite=True)

    def loadWeights(self, path):
        self.model.load_weights(path)

    def isolateVocals(self, path, fftWindowSize, phaseIterations=10):
        console.log("Attempting to isolate vocals from", path)
        audio, sampleRate = conversion.loadAudioFile(path)
        spectrogram, phase = conversion.audioFileToSpectrogram(
            audio, fftWindowSize=fftWindowSize)
        console.log("Retrieved spectrogram; processing...")

        chopper = Chopper()
        chopper.name = "infere"
        chopper.params = "{'scale': %d}" % self.config.inference_slice
        chop = chopper.get()

        slices = chop(spectrogram)

        normalizer = Normalizer()
        normalize = normalizer.get(both=False)
        denormalize = normalizer.get_reverse()

        newSpectrogram = np.zeros((spectrogram.shape[0], 0))
        for slice in slices:
            # normalize
            slice, norm = normalize(slice)
            expandedSpectrogram = conversion.expandToGrid(
                slice, self.peakDownscaleFactor)
            expandedSpectrogramWithBatchAndChannels = \
                expandedSpectrogram[np.newaxis, :, :, np.newaxis]

            predictedSpectrogramWithBatchAndChannels = self.model.predict(
                expandedSpectrogramWithBatchAndChannels)
            # o /// o
            predictedSpectrogram = \
                predictedSpectrogramWithBatchAndChannels[0, :, :, 0]
            localSpectrogram = predictedSpectrogram[:slice.shape[0],
                                                    :slice.shape[1]]
            # de-normalize spectrogram
            localSpectrogram = denormalize(localSpectrogram, norm)
            newSpectrogram = np.concatenate((newSpectrogram, localSpectrogram),
                                            axis=1)

        console.log("Processed spectrogram; reconverting to audio")

        # save original spectrogram as image
        pathParts = os.path.split(path)
        fileNameParts = os.path.splitext(pathParts[1])
        conversion.saveSpectrogram(spectrogram, os.path.join(
            pathParts[0], fileNameParts[0]) + ".png")

        # save network output
        self.saveAudio(newSpectrogram,
                       fftWindowSize,
                       phaseIterations,
                       sampleRate,
                       path,
                       vocal=not self.config.instrumental)

        # save difference
        self.saveAudio(spectrogram - newSpectrogram,
                       fftWindowSize,
                       phaseIterations,
                       sampleRate,
                       path,
                       vocal=self.config.instrumental)

        console.log("Vocal isolation complete")

    def saveAudio(self, spectrogram, fftWindowSize,
                  phaseIterations, sampleRate,
                  path, vocal=True):
        part = "_vocal" if vocal else "_instrumental"
        newAudio = conversion.spectrogramToAudioFile(
                spectrogram,
                fftWindowSize=fftWindowSize,
                phaseIterations=phaseIterations)
        pathParts = os.path.split(path)
        fileNameParts = os.path.splitext(pathParts[1])
        outputFileNameBase = os.path.join(
            pathParts[0], fileNameParts[0] + part)
        console.log("Converted to audio; writing to",
                    outputFileNameBase + ".wav")

        conversion.saveAudioFile(
            newAudio, outputFileNameBase + ".wav", sampleRate)
        conversion.saveSpectrogram(spectrogram, outputFileNameBase + ".png")


if __name__ == "__main__":
    files = sys.argv[1:]
    config_str = str(config)
    print(config_str)
    # save current environment for later usage
    with open("./envs/last", "w") as f:
        f.write(config_str)

    acapellabot = AcapellaBot(config)

    if len(files) == 0 and config.data:
        console.log("No files provided; attempting to train on " +
                    config.data + "...")
        if config.load:
            console.h1("Loading Weights")
            acapellabot.loadWeights(config.weights)
        console.h1("Loading Data")
        data = Data()
        console.h1("Training Model")
        acapellabot.train(data, config.epochs,
                          config.batch, config.start_epoch)
        acapellabot.saveWeights(config.weights)
    elif len(files) > 0:
        console.log("Weights provided; performing inference on " +
                    str(files) + "...")
        console.h1("Loading weights")
        acapellabot.loadWeights(config.weights)
        for f in files:
            acapellabot.isolateVocals(f, config.fft, config.phase)
    else:
        console.error(
            "Please provide data to train on (--data) or files to infer on")
