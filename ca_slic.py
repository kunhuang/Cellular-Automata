import os
base_path = os.getcwd()+'/'

import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import numpy as np
from numpy import linalg as LA
from numpy.linalg import inv
import matplotlib.cm as cm
import time
from PIL import Image
import sys
import math
import pdb
from skimage.segmentation import slic
from skimage.segmentation import mark_boundaries
from skimage.util import img_as_float
from skimage import io
import matplotlib.pyplot as plt
import argparse


def rgb2gray(rgb):
    return np.dot(rgb[...,:3], [0.299, 0.587, 0.114])

def get_background_indexs(image, output_image_path, quantile=0.15, ignored_indexs=None):
    # not a gray scale
    if ignored_indexs is None:
        ignored_indexs = []
    if len(image.shape)>2 and image.shape[2] > 1:
        image = rgb2gray(image) 
    
    image_flat = image.flatten()
    # set as maximum to be ignored
    image_flat[ignored_indexs] = 2.0
    indexs = np.argsort(image_flat)[:quantile*image_flat.size]
    
    background_image_flat = np.ones((image.shape[0]*image.shape[1]))
    background_image_flat[indexs] = 0
    background_image = background_image_flat.reshape((image.shape[0], image.shape[1]))
    output_image_PIL = Image.fromarray((background_image*255.).astype(np.uint8))
    output_image_path = output_image_path[:-4]+'-background'+output_image_path[-4:]
    output_image_PIL.save(output_image_path)
    
    return indexs
    
def get_foreground_indexs(image, output_image_path, quantile=0.01, ignored_indexs=None):
    if ignored_indexs is None:
        ignored_indexs = []
    # not a gray scale
    if len(image.shape)>2 and image.shape[2] > 1:
        image = rgb2gray(image) 
    
    image_flat = image.flatten()
    image_flat[ignored_indexs] = -1.0
    indexs = np.argsort(image_flat,)[-quantile*image_flat.size:]

    foreground_image_flat = np.ones((image.shape[0]*image.shape[1]))
    foreground_image_flat[indexs] = 0
    foreground_image = foreground_image_flat.reshape((image.shape[0], image.shape[1]))
    output_image_PIL = Image.fromarray((foreground_image*255.).astype(np.uint8))
    output_image_path = output_image_path[:-4]+'-foreground'+output_image_path[-4:]
    output_image_PIL.save(output_image_path)
    
    return indexs

def unique_append(l, e):
    if e not in l:
        l.append(e)

def get_superpixel(image, num_segments=100):
    """
    Args:
        image(N*M array):
    
    Returns:
        labels(N*M array), new_neighbors(n*[int]), new_rgb(n*[int, int, int])
    """

    (N, M, _) = image.shape

    labels = slic(image, n_segments = num_segments, sigma = 5)
    
    # Show segmentation
    # fig = plt.figure("Superpixels -- %d segments" % (num_segments))
    # ax = fig.add_subplot(1, 1, 1)
    # ax.imshow(mark_boundaries(image, labels))
    # plt.axis("off")
    # plt.show()

    n_labels = np.max(labels)+1

    new_neighbors = [[] for i in xrange(n_labels)]
    new_rgb = np.zeros((n_labels, 3))
    label_count = n_labels*[0]
    
    for i in xrange(N):
        for j in xrange(M):
            if j < M-1 and labels[i, j] != labels[i, j+1]:
                unique_append(new_neighbors[labels[i, j]], labels[i, j+1])
                unique_append(new_neighbors[labels[i, j+1]], labels[i, j])
            if i < N-1 and j < M-1 and labels[i, j] != labels[i+1, j+1]:
                unique_append(new_neighbors[labels[i, j]], labels[i+1, j+1])
                unique_append(new_neighbors[labels[i+1, j+1]], labels[i, j])
            if i < N-1 and labels[i, j] != labels[i+1, j]:
                unique_append(new_neighbors[labels[i, j]], labels[i+1, j])
                unique_append(new_neighbors[labels[i+1, j]], labels[i, j])
            new_rgb[labels[i, j],:] += image[i,j,:]
            label_count[labels[i, j]] += 1

    for i in xrange(n_labels):
        new_rgb[i] /= label_count[i]

    return labels, new_neighbors, new_rgb

def get_super_index(labels, foreground_indexs, background_indexs):
    """
    Args:
        labels(N*M array):

        foreground_indexs([int]):

        background_indexs([int]):

    Returns:
        super_foreground_indexs([int]), super_background_indexs([int])

    """
    labels_flatten = labels.flatten()
    n_labels = np.max(labels)+1
    super_background_indexs = []
    super_foreground_indexs = []
    for index in background_indexs:
        unique_append(super_background_indexs, labels_flatten[index])
    for index in foreground_indexs:
        unique_append(super_foreground_indexs, labels_flatten[index])

    # remove overlap from background
    super_background_indexs = [index for index in super_background_indexs if index not in foreground_indexs]

    return super_foreground_indexs, super_background_indexs

def get_salience_indexs(saliency, threshold=0.75):
    saliency_flatten = saliency.flatten()
    return [i for i in xrange(len(saliency_flatten)) if saliency_flatten[i] > threshold]

def ca(neighbors, rgbs, fg_indexs, bg_indexs, sigma_3_square=0.1, a=0.6, b=0.2, num_step=10, fg_bias=0.3, bg_bias=-0.3):
    """

    Returns:
        super_saliency()
    """
    N = len(neighbors)

    F = np.asmatrix(np.zeros((N, N)))
    f = lambda c1, c2: np.exp(-LA.norm(c1-c2)/(sigma_3_square))
    scale_to_1 = lambda x: (x-np.min(x))/(np.max(x)-np.min(x))
    other_indexs = [i for i in range(N) if (i not in fg_indexs and i not in bg_indexs)]
    
    for i in xrange(len(neighbors)):
        for j in neighbors[i]:
            F[j, i] = F[i, j] = f(rgbs[i,:], rgbs[j, :])
        D = np.asmatrix(np.diag(np.asarray(np.sum(F, axis=1)).flatten()))

    F_star = inv(D)*F

    C_diag = np.asarray(np.divide(1, np.max(F, axis=1))).flatten()
    C_max, C_min = np.max(C_diag), np.min(C_diag)
    C_star_diag = a*(C_diag-C_min)/(C_max-C_min)+b
    C_star = np.asmatrix(np.diag(C_star_diag))
    
    S_0 = 0.5*np.ones((N, 1))
    S_0 = np.asmatrix(S_0)
    S = S_0

    func = lambda x: 1. if x > 1. else (0. if x < 0. else x)
    
    for i in xrange(num_step):
        S[fg_indexs] += fg_bias
        S[bg_indexs] += bg_bias
    
        S_new = C_star*S + (np.identity(N)-C_star)*F_star*S
        if len(other_indexs) > 0:
            S_new[other_indexs] = scale_to_1(S_new[other_indexs])
        S_new = np.vectorize(func)(S_new)

        print i, "iteration"
        print "Norm of difference:", LA.norm(S_new-S)
        S = S_new

    for i in xrange(num_step):    
        S_new = C_star*S + (np.identity(N)-C_star)*F_star*S
        S_new = scale_to_1(S_new)
        print i, "iteration"
        print "Norm of difference:", LA.norm(S_new-S)
        S = S_new

    return S

def get_saliency(labels, super_saliency):
    n_labels = len(super_saliency)
    
    labels_flatten = labels.flatten()
    saliency_flatten = np.zeros(labels_flatten.shape)

    for i in xrange(n_labels):
        indexs = np.argwhere(labels_flatten==i)
        saliency_flatten[indexs] = super_saliency[i]

    return saliency_flatten.reshape(labels.shape)

def cut_saliency(image, salience_indexs):
    flatten = image.reshape(image.shape[0]*image.shape[1],3)
    flatten[salience_indexs, :] = 0
    return flatten.reshape(image.shape)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise ValueError("Please input the image file and saliency file")

    image_file, saliency_image_file = sys.argv[1], sys.argv[2]
    after_cut_name = sys.argv[3]

    output_image_name = sys.argv[4]
    # output_directory = sys.argv[6]
    
    input_image_path = base_path+image_file
    saliency_image_path = base_path+saliency_image_file
    # output_image_path = base_path+output_directory+'/'+saliency_image_file.split('/')[-1][:-4]+'.bmp'
    output_image_path = base_path+output_image_name

    image = img_as_float(io.imread(input_image_path))
    saliency_image = img_as_float(io.imread(saliency_image_path))

    foreground_indexs = get_foreground_indexs(saliency_image, output_image_path) 
    background_indexs = get_background_indexs(saliency_image, output_image_path) 

    labels, neighbors, rgbs = get_superpixel(image)
    super_foreground_indexs, super_background_indexs = get_super_index(labels, foreground_indexs, background_indexs)

    super_saliency = ca(neighbors, rgbs, super_foreground_indexs, super_background_indexs)
    saliency = get_saliency(labels, super_saliency)

    # plt.imshow(saliency, cmap=plt.get_cmap('gray'))
    # plt.show()

    io.imsave(output_image_path, saliency)

    salience_indexs = get_salience_indexs(saliency, threshold=0.75)

    io.imsave(after_cut_name, cut_saliency(image, salience_indexs))