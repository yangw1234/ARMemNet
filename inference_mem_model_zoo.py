import tensorflow as tf
from tensorflow.contrib import layers
import os
from utils import make_date_dir, find_latest_dir

import sys
from zoo.pipeline.api.net import TFNet
from zoo import init_nncontext, Sample
import tensorflow as tf
import numpy as np
from optparse import OptionParser
from data_utils import load_agg_selected_data_mem
from AR_mem.config import Config
from AR_mem.model import Model


PARALLELISM=4
BATCH_PER_THREAD=32


if __name__ == "__main__":
    config = Config()
    config.data_path = "/home/yang/sources/zoo/aggregated_data_5min_scaled.csv"
    config.model_dir = "/home/yang/sources/zoo/model/model_save"
    config.latest_model=False

    model = Model(config)

    # init or get SparkContext
    sc = init_nncontext()

    # create test data
    _, _, test_x, _, _, test_y, _, _, test_m, test_dt = \
        load_agg_selected_data_mem(data_path=config.data_path,
                                   x_len=config.x_len,
                                   y_len=config.y_len,
                                   foresight=config.foresight,
                                   cell_ids=config.test_cell_ids,
                                   dev_ratio=config.dev_ratio,
                                   test_len=config.test_len,
                                   seed=config.seed)

    # get model dir
    if config.latest_model:
        model_dir = find_latest_dir(os.path.join(config.model_dir, 'model_save/'))
    else:
        if not config.model_dir:
            raise Exception("model_dir or latest_model=True should be defined in config")
        model_dir = config.model_dir

    #  export a TensorFlow model to frozen inference graph.
    with tf.Session() as sess:
        saver = tf.train.Saver()
        saver.restore(sess, os.path.join(model_dir, config.model))

        tfnet = TFNet.from_session(sess,
                                   inputs=[model.input_x, model.memories], # dropout is never used
                                   outputs=[model.predictions])

    data_x_rdd = sc.parallelize(test_x, PARALLELISM)
    data_m_rdd = sc.parallelize(test_m, PARALLELISM)

    # create a RDD of Sample
    sample_rdd = data_x_rdd.zip(data_m_rdd).map(
        lambda x: Sample.from_ndarray(features=x,
                                      labels=np.zeros([1])))

    # distributed inference on Spark and return an RDD
    outputs = tfnet.predict(sample_rdd,
                            batch_per_thread=1022,
                            distributed=True)

    result_dir = make_date_dir(os.path.join(config.model, 'results/'))

    outputs.saveAsTextFile(os.path.join(result_dir, "result.txt"))

    # collect the RDD to trigger execution
    result_zoo = np.array(outputs.collect())

    # compare tensorflow result with zoo result
    result_tensorflow = np.load(os.path.join(find_latest_dir(os.path.join("/home/yang/sources/ARMemNet/AR_mem/", "results/")), "pred.npy"))

    print("Is the two results equal? ", np.allclose(result_tensorflow, np.array(result_zoo), 0, 1e-6))

