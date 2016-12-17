# Created by albert aparicio on 21/11/16
# coding: utf-8

# This script defines an encoder-decoder GRU-RNN model
# to map the source's sequence parameters to the target's sequence parameters

# This import makes Python use 'print' as in Python 3.x
from __future__ import print_function

import h5py
import numpy as np
import tfglib.seq2seq_datatable as s2s
from keras.layers import GRU, Dropout, TimeDistributed, Input, Dense
from keras.layers.core import RepeatVector
from keras.models import Model
from keras.optimizers import Adam
from keras.utils.generic_utils import Progbar
from tfglib.seq2seq_normalize import maxmin_scaling

#######################
# Sizes and constants #
#######################
# Batch shape
batch_size = 200
output_dim = 44
data_dim = output_dim + 10 + 10

# Other constants
nb_epochs = 50
# lahead = 1  # number of elements ahead that are used to make the prediction
learning_rate = 0.001
validation_fraction = 0.25

#############
# Load data #
#############
# Switch to decide if datatable must be built or can be loaded from a file
build_datatable = False

print('Preparing data\n' + '=' * 8 * 5)
if build_datatable:
    # Build datatable of training and test data
    # (data is already encoded with Ahocoder)
    print('Saving training datatable...', end='')
    (src_train_datatable,
     src_train_masks,
     trg_train_datatable,
     trg_train_masks,
     max_train_length,
     train_speakers_max,
     train_speakers_min
     ) = s2s.seq2seq_save_datatable(
        'data/training/',
        'data/seq2seq_train_datatable'
    )
    print('done')

    print('Saving test datatable...', end='')
    (src_test_datatable,
     src_test_masks,
     trg_test_datatable,
     trg_test_masks,
     max_test_length,
     test_speakers_max,
     test_speakers_min
     ) = s2s.seq2seq_save_datatable(
        'data/test/',
        'data/seq2seq_test_datatable'
    )
    print('done')

else:
    # Retrieve datatables from .h5 files
    print('Loading training datatable...', end='')
    (src_train_datatable,
     src_train_masks,
     trg_train_datatable,
     trg_train_masks,
     max_train_length,
     train_speakers_max,
     train_speakers_min
     ) = s2s.seq2seq2_load_datatable(
        'data/seq2seq_train_datatable.h5'
    )
    print('done')

##################
# Normalize data #
##################
# Iterate over sequence 'slices'
assert src_train_datatable.shape[0] == trg_train_datatable.shape[0]

for i in range(src_train_datatable.shape[0]):
    (
        src_train_datatable[i, :, 0:42],
        trg_train_datatable[i, :, 0:42]
    ) = maxmin_scaling(
        src_train_datatable[i, :, :],
        src_train_masks[i, :],
        trg_train_datatable[i, :, :],
        trg_train_masks[i, :],
        train_speakers_max,
        train_speakers_min
    )

################################################
# Split data into training and validation sets #
################################################
# ###################################
# # TODO ELIMINATE AFTER DEVELOPING #
# ###################################
# batch_size = 2
# nb_epochs = 2
#
# num = 10
# src_train_datatable = src_train_datatable[0:num]
# src_train_masks = src_train_masks[0:num]
# trg_train_datatable = trg_train_datatable[0:num]
# trg_train_masks = trg_train_masks[0:num]
# #################################################

src_train_data = src_train_datatable[0:int(np.floor(
    src_train_datatable.shape[0] * (1 - validation_fraction)))]
src_valid_data = src_train_datatable[int(np.floor(
    src_train_datatable.shape[0] * (1 - validation_fraction))):]

trg_train_data = trg_train_datatable[0:int(np.floor(
    trg_train_datatable.shape[0] * (1 - validation_fraction)))]
trg_train_masks_f = trg_train_masks[0:int(np.floor(
    trg_train_masks.shape[0] * (1 - validation_fraction)))]

trg_valid_data = trg_train_datatable[int(np.floor(
    trg_train_datatable.shape[0] * (1 - validation_fraction))):]
trg_valid_masks_f = trg_train_masks[int(np.floor(
    trg_train_masks.shape[0] * (1 - validation_fraction))):]

################
# Define Model #
################
print('Initializing model\n' + '=' * 8 * 5)
main_input = Input(shape=(max_train_length, data_dim),
                   dtype='float32',
                   name='main_input'
                   )
encoder_GRU = GRU(
    output_dim=100,
    # input_shape=(max_train_length, data_dim),
    return_sequences=False,
    consume_less='gpu'
)(main_input)

repeat_layer = RepeatVector(max_train_length)(encoder_GRU)

decoder_GRU = GRU(100, return_sequences=True, consume_less='gpu')(repeat_layer)

dropout_layer = Dropout(0.5)(decoder_GRU)

parameters_GRU = GRU(
    output_dim - 2,
    return_sequences=True,
    consume_less='gpu',
    activation='linear',
    name='params_output'
)(dropout_layer)

flags_GRU = TimeDistributed(Dense(
    2,
    # consume_less='gpu',
    activation='sigmoid',
    # TODO rename layer
    # name='flags_output'
), name='flags_output')(dropout_layer)

model = Model(input=main_input, output=[parameters_GRU, flags_GRU])

optimizer_name = 'adam'
adam = Adam(clipnorm=10)
params_loss = 'mse'
flags_loss = 'binary_crossentropy'

model.compile(optimizer=adam,
              loss={'params_output': params_loss,
                    'flags_output': flags_loss},
              sample_weight_mode="temporal"
              )

###############
# Train model #
###############
print('Training\n' + '=' * 8 * 5)

training_history = []
validation_history = []

for epoch in range(nb_epochs):
    print('Epoch {} of {}'.format(epoch + 1, nb_epochs))

    nb_batches = int(src_train_data.shape[0] / batch_size)
    progress_bar = Progbar(target=nb_batches)

    epoch_train_partial_loss = []

    try:
        progress_bar.update(0)
    except OverflowError as err:
        raise Exception('nb_batches is 0. Please check the training data')

    for index in range(nb_batches):
        # Get batch of sequences and masks
        src_batch = src_train_data[
                    index * batch_size:(index + 1) * batch_size]
        trg_batch = trg_train_data[
                    index * batch_size:(index + 1) * batch_size]
        batch_masks = trg_train_masks_f[
                      index * batch_size:(index + 1) * batch_size]

        epoch_train_partial_loss.append(
            model.train_on_batch(
                {'main_input': src_batch},
                {'params_output': trg_batch[:, :, 0:42],
                 'flags_output': trg_batch[:, :, 42:44]},
                sample_weight={'params_output': batch_masks,
                               'flags_output': batch_masks}
            )
        )

        progress_bar.update(index + 1)

    epoch_val_loss = model.evaluate(
        src_valid_data,
        {'params_output': trg_valid_data[:, :, 0:42],
         'flags_output': trg_valid_data[:, :, 42:44]},
        batch_size=batch_size,
        sample_weight={'params_output': trg_valid_masks_f,
                       'flags_output': trg_valid_masks_f},
        verbose=0
    )

    epoch_train_loss = np.mean(np.array(epoch_train_partial_loss), axis=0)

    training_history.append(epoch_train_loss)
    validation_history.append(epoch_val_loss)

    # Generate epoch report
    print('loss: ' + str(training_history[-1]) +
          ' - val_loss: ' + str(validation_history[-1]) +
          '\n'  # + '-' * 24
          )
    print()

###############
# Saving data #
###############
print('Saving model\n' + '=' * 8 * 5)
model.save_weights(
    'models/seq2seq_' + params_loss + '_' + flags_loss + '_' + optimizer_name +
    '_epochs_' + str(nb_epochs) + '_lr_' + str(learning_rate) + '_weights.h5')

with open('models/seq2seq_' + params_loss + '_' + flags_loss + '_' +
                  optimizer_name + '_epochs_' + str(nb_epochs) + '_lr_' +
                  str(learning_rate) + '_model.json', 'w'
          ) as model_json:
    model_json.write(model.to_json())

print('Saving training parameters\n' + '=' * 8 * 5)
with h5py.File('training_results/seq2seq_training_params.h5', 'w') as f:
    f.attrs.create('params_loss', np.string_(params_loss))
    f.attrs.create('flags_loss', np.string_(flags_loss))
    f.attrs.create('optimizer', np.string_(optimizer_name))
    f.attrs.create('epochs', nb_epochs, dtype=int)
    f.attrs.create('learning_rate', learning_rate)
    f.attrs.create('train_speakers_max', train_speakers_max)
    f.attrs.create('train_speakers_min', train_speakers_min)
    f.attrs.create('metrics_names', model.metrics_names)

print('Saving training results')
np.savetxt('training_results/seq2seq_' + params_loss + '_' + flags_loss + '_' +
           optimizer_name + '_epochs_' + str(nb_epochs) + '_lr_' +
           str(learning_rate) + '_epochs.csv',
           np.arange(nb_epochs), delimiter=',')
np.savetxt('training_results/seq2seq_' + params_loss + '_' + flags_loss + '_' +
           optimizer_name + '_epochs_' + str(nb_epochs) + '_lr_' +
           str(learning_rate) + '_loss.csv',
           training_history, delimiter=',')
np.savetxt('training_results/seq2seq_' + params_loss + '_' + flags_loss + '_' +
           optimizer_name + '_epochs_' + str(nb_epochs) + '_lr_' +
           str(learning_rate) + '_val_loss.csv',
           validation_history, delimiter=',')

print('========================' + '\n' +
      '======= FINISHED =======' + '\n' +
      '========================')

exit()
