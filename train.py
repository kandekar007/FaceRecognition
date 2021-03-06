import bz2

import os
from model import create_model
from keras import backend as K
from keras.models import Model
from keras.layers import Input, Layer
from urllib.request import urlopen

import pickle

from data import triplet_generator

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from align import AlignDlib
import cv2

from sklearn.model_selection import GridSearchCV

import warnings
# Suppress LabelEncoder warning
warnings.filterwarnings('ignore')

from sklearn.preprocessing import LabelEncoder
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import LinearSVC

from sklearn.metrics import f1_score, accuracy_score

import numpy as np
import os.path

def download_landmarks(dst_file):
    url = 'http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2'
    decompressor = bz2.BZ2Decompressor()

    with urlopen(url) as src, open(dst_file, 'wb') as dst:
        data = src.read(1024)
        while len(data) > 0:
            dst.write(decompressor.decompress(data))
            data = src.read(1024)

dst_dir = 'models'
dst_file = os.path.join(dst_dir, 'landmarks.dat')

if not os.path.exists(dst_file):
    os.makedirs(dst_dir)
    download_landmarks(dst_file)

print("Initialised")

nn4_small2 = create_model()



# Input for anchor, positive and negative images
in_a = Input(shape=(96, 96, 3))
in_p = Input(shape=(96, 96, 3))
in_n = Input(shape=(96, 96, 3))

# Output for anchor, positive and negative embedding vectors
# The nn4_small model instance is shared (Siamese network)
emb_a = nn4_small2(in_a)
emb_p = nn4_small2(in_p)
emb_n = nn4_small2(in_n)

def load_image(path):
    img = cv2.imread(path, 1)
    # OpenCV loads images with color channels
    # in BGR order. So we need to reverse them
    return img[...,::-1]


class TripletLossLayer(Layer):
    def __init__(self, alpha, **kwargs):
        self.alpha = alpha
        super(TripletLossLayer, self).__init__(**kwargs)

    def triplet_loss(self, inputs):
        a, p, n = inputs
        p_dist = K.sum(K.square(a-p), axis=-1)
        n_dist = K.sum(K.square(a-n), axis=-1)
        return K.sum(K.maximum(p_dist - n_dist + self.alpha, 0), axis=0)

    def call(self, inputs):
        loss = self.triplet_loss(inputs)
        self.add_loss(loss)
        return loss

# Layer that computes the triplet loss from anchor, positive and negative embedding vectors
triplet_loss_layer = TripletLossLayer(alpha=0.2, name='triplet_loss_layer')([emb_a, emb_p, emb_n])

# Model that can be trained with anchor, positive negative images
nn4_small2_train = Model([in_a, in_p, in_n], triplet_loss_layer)


nn4_small2_pretrained = create_model()
nn4_small2_pretrained.load_weights('weights/nn4.small2.v1.h5')



class IdentityMetadata():
    def __init__(self, base, name, file):
        # dataset base directory
        self.base = base
        # identity name
        self.name = name
        # image file name
        self.file = file

    def __repr__(self):
        return self.image_path()

    def image_path(self):
        return os.path.join(self.base, self.name, self.file)

def load_metadata(path):
    metadata = []
    for i in sorted(os.listdir(path)):
        for f in sorted(os.listdir(os.path.join(path, i))):
            # Check file extension. Allow only jpg/jpeg' files.
            ext = os.path.splitext(f)[1]
            if ext == '.jpg' or ext == '.jpeg':
                metadata.append(IdentityMetadata(path, i, f))
    return np.array(metadata)

metadata = load_metadata('images')

alignment = AlignDlib('models/landmarks.dat')

def align_image(img):

    return alignment.align(96, img, alignment.getLargestFaceBoundingBox(img),
                           landmarkIndices=AlignDlib.OUTER_EYES_AND_NOSE)

embedded = np.zeros((metadata.shape[0], 128))
#print("Meta ",metadata.shape)
for i, m in enumerate(metadata):
    img = load_image(m.image_path())
    img = align_image(img)
    try:
        img = (img / 255.).astype(np.float32)
        em = nn4_small2_pretrained.predict(np.expand_dims(img, axis=0))
        #print("em--",em.shape)
        # obtain embedding vector for image
        embedded[i] = em[0]
    except:
        pass
def distance(emb1, emb2):
    return np.sum(np.square(emb1 - emb2))

print("distances calculated")

targets = np.array([m.name for m in metadata])

encoder = LabelEncoder()
encoder.fit(targets)

# Numerical encoding of identities
y = encoder.transform(targets)
encoderfile = "encoder.sav"
pickle.dump(encoder, open(encoderfile, 'wb'))

train_idx = np.arange(metadata.shape[0]) % 2 != 0
test_idx = np.arange(metadata.shape[0]) % 2 == 0

# 50 train examples of 10 identities (5 examples each)
X_train = embedded[train_idx]
# 50 test examples of 10 identities (5 examples each)
X_test = embedded[test_idx]

y_train = y[train_idx]
y_test = y[test_idx]
modelfile = "svm_one.sav"

grid={"C": [0.05,0.5,1,1.5,2,5,10], "loss": ["hinge", "squared_hinge"], "class_weight": [None,"balanced"]}

#knn = KNeighborsClassifier(n_neighbors=1, metric='euclidean')
if(os.path.exists(modelfile) == False):
    svc = GridSearchCV(LinearSVC(), grid, scoring="accuracy", cv=3).fit(X_train, y_train)
    #svc = LinearSVC()
    #knn.fit(X_train, y_train)
    #svc.fit(X_train, y_train)

    pickle.dump(svc, open(modelfile, 'wb'))

    #acc_knn = accuracy_score(y_test, knn.predict(X_test))
    acc_svc = accuracy_score(y_test, svc.predict(X_test))

    print(f'SVM accuracy = {acc_svc}')
else:
	svc = LinearSVC()
	svc = pickle.load(open(modelfile, 'rb'))
example_idx = 3
example_image = load_image(metadata[test_idx][example_idx].image_path())
print(embedded[test_idx][example_idx].shape)
"""example_prediction = svc.predict( [ embedded[test_idx][example_idx] ] )
example_identity = encoder.inverse_transform(example_prediction)[0]
print("recognised as", example_identity)
cv2.imshow("example",example_image)
cv2.waitKey(0)"""
