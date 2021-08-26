import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import os
import wandb

# wandb.offline
os.environ['WANDB_SILENT']="true"
wandb.login(key=str('14734fe9c5574e019e8f517149a20d6fe1b2fd0d'))
config = wandb.config
# run = wandb.init(project='WBtest', config={'wandb_nb':'wandb_three_in_one_hm'})
run = wandb.init(project='Raindrop', entity='xiang_zhang', config={'wandb_nb':'wandb_three_in_one_hm'})


from sklearn.metrics import roc_auc_score, classification_report, confusion_matrix
from sklearn.metrics import average_precision_score

import sys
# os.path.abspath('../')
# sys.path.append(os.path.abspath('../'))
from models_baselines import TransformerModel, TransformerModel2
from utils_baselines import *

# from utils_phy12 import *

torch.manual_seed(1)

# training modes
arch = 'standard'


model_path = '../models/'

base_path = '../P12data'
# ### show the names of variables and statistic descriptors
# ts_params = np.load(base_path + '/processed_data/ts_params.npy', allow_pickle=True)
# extended_static_params = np.load(base_path + '/processed_data/extended_static_params.npy', allow_pickle=True)
# print('ts_params: ', ts_params)
# print('extended_static_params: ', extended_static_params)

# """Xiang"""
# base_path = '../Theo/Transformer-Irregular'
ts_params= ['ALP', 'ALT', 'AST', 'Albumin', 'BUN', 'Bilirubin', 'Cholesterol', 'Creatinine',
 'DiasABP', 'FiO2', 'GCS', 'Glucose', 'HCO3', 'HCT', 'HR', 'K', 'Lactate', 'MAP',
 'MechVent', 'Mg', 'NIDiasABP', 'NIMAP', 'NISysABP', 'Na', 'PaCO2', 'PaO2',
 'Platelets', 'RespRate', 'SaO2', 'SysABP', 'Temp', 'TroponinI', 'TroponinT',
 'Urine', 'WBC', 'pH']
extended_static_params=['Age', 'Gender=0', 'Gender=1', 'Height', 'ICUType=1', 'ICUType=2', 'ICUType=3',
 'ICUType=4', 'Weight']

# training/model params
num_epochs = 20
learning_rate = 0.001

d_static = 9
# emb_len     = 10

d_inp = 36 * 2 # concat mask in mask_normalize function
# d_inp = 36*1  # doesn't has concat mask

d_model = 64  # 256
nhid = 2 * d_model
# nhid = 256
# nhid = 512  # seems to work better than 2*d_model=256
# nhid = 1024
nlayers = 1 #2  # the layer doesn't really matters

# nhead = 16 # seems to work better
nhead = 4  # 8, 16, 32

dropout = 0.3

max_len = 215

aggreg = 'mean'
# aggreg = 'max'

n_classes = 2
# MAX = d_model
MAX = 100

n_runs = 1  # change this from 1 to 1, in order to save debugging time.
n_splits = 1  # change this from 5 to 1, in order to save debugging time.
subset = False  # use subset for better debugging in local PC, which only contains 1200 patients

acc_arr = np.zeros((n_splits, n_runs))
auprc_arr = np.zeros((n_splits, n_runs))
auroc_arr = np.zeros((n_splits, n_runs))
for k in range(n_splits):
    split_idx = k + 1
    print('Split id: %d' % split_idx)
    if subset==True:
        split_path = '/splits/phy12_split_subset' + str(split_idx) + '.npy'
    else:
        split_path = '/splits/phy12_split' + str(split_idx) + '.npy'

    # prepare the data
    Ptrain, Pval, Ptest, ytrain, yval, ytest = get_data_split(base_path, split_path)
    print(len(Ptrain), len(Pval), len(Ptest), len(ytrain), len(yval), len(ytest))

    # """New split"""
    # normalization = False
    # imputation_method = None  # possible values: None, 'mean', 'forward', 'kNN', 'MICE' (slow execution), 'CubicSpline'
    # split_type = 'random'  # possible values: 'random', 'age', 'gender'
    # feature_removal_level = 'set'  # possible values: 'sample', 'set'
    # # missing_ratio = 0.0     # ratio [0, 1] of missing variables in validation and test set
    #
    # (X_features_train, X_static_train, X_time_train, y_train), (X_features_val, X_static_val, X_time_val, y_val), (
    # X_features_test, X_static_test, X_time_test, y_test) = \
    #     read_and_prepare_data(base_path, split_path, normalization, feature_removal_level, missing_ratio,
    #                           imputation=imputation_method, split_type=split_type)

    T, F = Ptrain[0]['arr'].shape
    D = len(Ptrain[0]['extended_static'])
    print(T, F, D)

    # get mean, std stats from train set
    Ptrain_tensor = np.zeros((len(Ptrain), T, F))  # shape: (9600, 215, 36)
    Ptrain_static_tensor = np.zeros((len(Ptrain), D))  # shape: (9600, 9)

    # feed features to tensor. This step can be improved
    for i in range(len(Ptrain)):
        Ptrain_tensor[i] = Ptrain[i]['arr']
        Ptrain_static_tensor[i] = Ptrain[i]['extended_static']

    """Z-score Normalization. Before this step, we can remove Direct current shift (minus the average) """
    mf, stdf = getStats(Ptrain_tensor)
    ms, ss = getStats_static(Ptrain_static_tensor)

    Ptrain_tensor, Ptrain_static_tensor, Ptrain_time_tensor, ytrain_tensor = tensorize_normalize(Ptrain, ytrain, mf,
                                                                                                 stdf, ms, ss)
    Pval_tensor, Pval_static_tensor, Pval_time_tensor, yval_tensor = tensorize_normalize(Pval, yval, mf, stdf, ms, ss)
    Ptest_tensor, Ptest_static_tensor, Ptest_time_tensor, ytest_tensor = tensorize_normalize(Ptest, ytest, mf, stdf, ms,
                                                                                      ss)
    """After normalization, a large proportion (more than half) of the values are becoming 1."""
    print(Ptrain_tensor.shape, Ptrain_static_tensor.shape, Ptrain_time_tensor.shape, ytrain_tensor.shape)
    # the shapes are: torch.Size([960, 215, 72]) torch.Size([960, 9]) torch.Size([960, 215, 1]) torch.Size([960])

    # convert to (seq_len, batch, feats)
    Ptrain_tensor = Ptrain_tensor.permute(1, 0, 2)  # shape: [215, 960, 72]
    Pval_tensor = Pval_tensor.permute(1, 0, 2)
    Ptest_tensor = Ptest_tensor.permute(1, 0, 2)
    """Mask out some variables: [ 8, 14, 17, 20, 21, 22, 29, 30, 33] (sparse ratio>0.1)
    1. We train on all sensors, but testing with partial sensors
    2. Train and test on partial sensors. """
    # # variable = [ 8, 14, 17, 20, 21, 22, 29, 30, 33]  # AUROC =76.5 if only keep these variables
    #
    # # AUROC =83.9 if only keep these variables; AUROC =75.1 (simple_classifier) if remove these variables; 77.4 (set function)
    # variable = [ 8,  9, 10, 13, 14, 17, 18, 20, 21, 22, 24, 25, 27, 29, 30, 33, 35]
    #
    # # variable = [9, 10, 13, 18, 24, 25, 27, 35] # AUROC =79.7 if only keep these variables
    # for i in range(36):
    #     # if i not in variable:
    #     if i in variable:
    #     #     #Ptrain_tensor[:, :, i]=0
    #         Pval_tensor[:, :, i] = 0
    #         Ptest_tensor[:, :, i] = 0

    # convert to (seq_len, batch)
    Ptrain_time_tensor = Ptrain_time_tensor.squeeze(2).permute(1, 0)
    Pval_time_tensor = Pval_time_tensor.squeeze(2).permute(1, 0)
    Ptest_time_tensor = Ptest_time_tensor.squeeze(2).permute(1, 0)

    for m in range(n_runs):
        print('- - Run %d - -' % (m + 1))

        # instantiate model
        model = TransformerModel2(d_inp, d_model, nhead, nhid, nlayers, dropout, max_len,
                                  d_static, MAX, 0.5, aggreg, n_classes)

        #         model = TransformerModel2(d_inp, d_model, nhead, nhid, nlayers, dropout, max_len,
        #                                   d_static, MAX, 0.5, 'mean', n_classes)
        #         model = TransformerModel(d_inp, d_model, nhead, nhid, nlayers, dropout, max_len,
        #                                   d_static, MAX, n_classes)

        model = model.cuda()

        criterion = torch.nn.CrossEntropyLoss().cuda()

        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.1,
                                                               patience=1, threshold=0.0001, threshold_mode='rel',
                                                               cooldown=0, min_lr=1e-8, eps=1e-08, verbose=True)

        idx_0 = np.where(ytrain == 0)[0]
        idx_1 = np.where(ytrain == 1)[0]

        strategy = 2

        """Upsampling, increase the number of positive samples"""
        # Strategy 2: permute randomly each index set at each epoch, and expand x3 minority set
        n0, n1 = len(idx_0), len(idx_1)
        expanded_idx_1 = np.concatenate([idx_1, idx_1, idx_1], axis=0)
        expanded_n1 = len(expanded_idx_1)

        batch_size = 128  # balanced batch size
        if strategy == 1:
            n_batches = 10  # number of batches to process per epoch
        elif strategy == 2:
            K0 = n0 // int(batch_size / 2)
            K1 = expanded_n1 // int(batch_size / 2)
            n_batches = np.min([K0, K1])

        best_aupr_val = best_auc_val = 0.0
        print('Stop epochs: %d, Batches/epoch: %d, Total batches: %d' % (num_epochs, n_batches, num_epochs * n_batches))
        #         optimizer = NoamOpt(d_model, 5.0, 500, torch.optim.Adam(model.parameters(), lr=0, betas=(0.9, 0.98), eps=1e-9))

        start = time.time()

        wandb.watch(model)
        for epoch in range(num_epochs):
            model.train()

            if strategy == 2:
                """shuffle the index of positive and negative samples"""
                np.random.shuffle(expanded_idx_1)
                I1 = expanded_idx_1
                np.random.shuffle(idx_0)
                I0 = idx_0
                # # random shuffling of expanded_idx_1, idx_0
                # ep1 = np.random.permutation(expanded_n1)
                # p0 = np.random.permutation(n0)
                # I1 = expanded_idx_1[ep1]
                # I0 = idx_0[p0]
            """In each epoch, first shuffle the samples, then take the first n_batches*int(batch_size / 2) for training"""


            for n in range(n_batches):
                if strategy == 1:
                    idx = random_sample(idx_0, idx_1, batch_size)
                elif strategy == 2:
                    """In each batch=128, 64 positive samples, 64 negative samples"""
                    idx0_batch = I0[n * int(batch_size / 2):(n + 1) * int(batch_size / 2)]
                    idx1_batch = I1[n * int(batch_size / 2):(n + 1) * int(batch_size / 2)]
                    idx = np.concatenate([idx0_batch, idx1_batch], axis=0)

                P, Ptime, Pstatic, y = Ptrain_tensor[:, idx, :].cuda(), Ptrain_time_tensor[:, idx].cuda(), \
                                       Ptrain_static_tensor[idx].cuda(), ytrain_tensor[idx].cuda()

                """Shape [128]. Length means the number of timepoints in each sample, for all samples in this batch"""
                lengths = torch.sum(Ptime > 0, dim=0)

                """Use two different ways to check the results' consistency"""
                # outputs = model.forward(P, Pstatic, Ptime, lengths)
                outputs = evaluate_standard(model, P, Ptime, Pstatic)

                # if epoch == 0:
                #     optimizer.zero_grad()
                #     loss = criterion(outputs, y)
                # elif epoch>0:  # Don't train the model at epoch==0

                optimizer.zero_grad()
                loss = criterion(outputs, y)
                loss.backward()
                optimizer.step()
            """Training performance"""
            train_probs = torch.squeeze(torch.sigmoid(outputs))
            train_probs = train_probs.cpu().detach().numpy()
            train_y = y.cpu().detach().numpy()
            train_auroc = roc_auc_score(train_y, train_probs[:, 1])
            train_auprc = average_precision_score(train_y, train_probs[:, 1])
            # print("Train: Epoch %d, train loss:%.4f, train_auprc: %.2f, train_auroc: %.2f" % (
            # epoch, loss.item(),  train_auprc * 100, train_auroc * 100))

            wandb.log({ "train_loss": loss.item(), "train_auprc": train_auprc, "train_auroc": train_auroc})
            if epoch == 0 or epoch == num_epochs-1:
                print(confusion_matrix(train_y, np.argmax(train_probs, axis=1), labels=[0, 1]))
                # train_auc_val = roc_auc_score(y, probs[:, 1])
                # train_aupr_val = average_precision_score(y, probs[:, 1])


            """Use the last """
            """Validation"""
            model.eval()
            if epoch ==0 or epoch % 1 == 0:
                with torch.no_grad():
                    out_val = evaluate_standard(model, Pval_tensor, Pval_time_tensor, Pval_static_tensor)
                    out_val = torch.squeeze(torch.sigmoid(out_val))
                    out_val = out_val.detach().cpu().numpy()

                    # denoms = np.sum(np.exp(out_val), axis=1).reshape((-1, 1))
                    # probs = np.exp(out_val) / denoms
                    # ypred = np.argmax(out_val, axis=1)

                    val_loss = criterion(torch.from_numpy(out_val), torch.from_numpy(yval.squeeze(1)))

                    auc_val = roc_auc_score(yval, out_val[:, 1])
                    aupr_val = average_precision_score(yval, out_val[:, 1])
                    print("Validataion: Epoch %d,  val_loss:%.4f, aupr_val: %.2f, auc_val: %.2f" % (epoch,
                      val_loss.item(), aupr_val * 100, auc_val * 100))
                    # print(confusion_matrix(yval, np.argmax(out_val, axis=1),))

                    wandb.log({ "val_loss": val_loss.item(), "val_auprc": aupr_val,
                               "val_auroc": auc_val})


                    scheduler.step(aupr_val)
                    # save model
                    if aupr_val > best_aupr_val:
                        best_aupr_val = aupr_val
                    # if auc_val > best_auc_val:
                    #     best_auc_val = auc_val
                        print(
                            "**[S] Epoch %d, aupr_val: %.4f, auc_val: %.4f **" % (epoch, aupr_val * 100, auc_val * 100))
                        torch.save(model.state_dict(), model_path + arch + '_' + str(split_idx) + '.pt')

            # if epoch == 3:
            #     end = time.time()
            #     time_elapsed = end - start
            #     print('-- Estimated train time: %.3f mins --' % (time_elapsed / 60.0 / 4 * num_epochs))

        end = time.time()
        time_elapsed = end - start
        print('Total Time elapsed: %.3f mins' % (time_elapsed / 60.0))

        """testing"""
        model.load_state_dict(torch.load(model_path + arch + '_' + str(split_idx) + '.pt'))
        model.eval()

        with torch.no_grad():
            out_test = evaluate(model, Ptest_tensor, Ptest_time_tensor, Ptest_static_tensor).numpy()
            ypred = np.argmax(out_test, axis=1)


            denoms = np.sum(np.exp(out_test), axis=1).reshape((-1, 1))
            probs = np.exp(out_test) / denoms

            auc = roc_auc_score(ytest, probs[:, 1])
            aupr = average_precision_score(ytest, probs[:, 1])
            acc = np.sum(ytest.ravel() == ypred.ravel()) / ytest.shape[0]
            print('Testing: AUROC = %.2f | AUPRC = %.2f | Accuracy = %.2f' % (auc * 100, aupr * 100, acc * 100))
            print('classification report', classification_report(ytest, ypred))
            print(confusion_matrix(ytest, ypred, labels=[0, 1]))

        # store
        acc_arr[k, m] = acc * 100
        auprc_arr[k, m] = aupr * 100
        auroc_arr[k, m] = auc * 100

# pick best performer for each split based on max AUPRC
idx_max = np.argmax(auprc_arr, axis=1)
acc_vec = [acc_arr[k, idx_max[k]] for k in range(n_splits)]
auprc_vec = [auprc_arr[k, idx_max[k]] for k in range(n_splits)]
auroc_vec = [auroc_arr[k, idx_max[k]] for k in range(n_splits)]

# display mean and standard deviation
mean_acc, std_acc = np.mean(acc_vec), np.std(acc_vec)
mean_auprc, std_auprc = np.mean(auprc_vec), np.std(auprc_vec)
mean_auroc, std_auroc = np.mean(auroc_vec), np.std(auroc_vec)
print('------------------------------------------')
print('Accuracy = %.1f +/- %.1f' % (mean_acc, std_acc))
print('AUPRC    = %.1f +/- %.1f' % (mean_auprc, std_auprc))
print('AUROC    = %.1f +/- %.1f' % (mean_auroc, std_auroc))

# Mark the run as finished
wandb.finish()

# save in numpy file
np.save('./results/' + arch + '_phy12_setfunction.npy', [acc_vec, auprc_vec, auroc_vec])


