#!/usr/bin/python3
import datetime
from keras.callbacks import ModelCheckpoint, TensorBoard, Callback
from matplotlib.cm import get_cmap
from PIL import Image
import numpy as np
import os

from config import config


class Checkpointer(object):
    def __init__(self, bot):
        self.config = config
        self.checkpoints = self.config.checkpoints
        self.bot = bot

    def get(self):
        if not self.checkpoints:
            return []
        names = self.checkpoints.split(",")
        checkpoints = []
        for name in names:
            checkpoints.append(getattr(self, name.strip())())
        return checkpoints

    def tensorboard(self):
        date = datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
        log_dir = self.config.tensorboard + "/{}".format(date)
        log_dir = os.path.join(self.config.logs, log_dir)
        return TensorBoard(log_dir=log_dir)

    def weights(self):
        filepath = os.path.join(os.path.dirname(self.config.weights),
                                "best_weights.hdf5")
        if not os.path.isabs(filepath):
            filepath = os.path.join(self.config.logs, filepath)
        return ModelCheckpoint(filepath=filepath,
                               verbose=1,
                               save_best_only=True)

    def error_visualization(self):
        return ErrorVisualization(self.bot)


class ErrorVisualization(Callback):
    def __init__(self, bot):
        self.bot = bot

    def on_epoch_end(self, epoch, logs={}):
        xValid = self.bot.xValid
        yValid = self.bot.yValid

        error = np.zeros(yValid[0].shape)

        n = len(xValid) // 100
        for i in range(n):
            y_pred = self.bot.model.predict(xValid[i*100:(i+1)*100],
                                            batch_size=8)
            error += np.sum(np.square(y_pred - yValid[i*100:(i+1)*100]),
                            axis=0)

        error /= (100*n)
        error = error[:, :, 0]
        top_val = np.max(error)
        # scale to range 0, 1
        error /= top_val

        cm_hot = get_cmap('magma')
        im = cm_hot(error)

        # scale to range 0, 255
        im = np.uint8(im * 255)

        im = Image.fromarray(im)
        image_path = os.path.join(self.bot.config.logs, "images")
        if not os.path.exists(image_path):
            os.mkdir(image_path)
        im.save("%s/error%03d-%f.png" % (image_path, epoch, top_val),
                format='PNG')