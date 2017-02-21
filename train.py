import tensorflow as tf
import numpy as np
import model
import argparse
import pickle
from os.path import join
import h5py
from Utils import image_processing
import scipy.misc
import random
import json
import os
import shutil
from pycocotools.coco import COCO


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('--z_dim', type=int, default=100,
						help='Noise dimension')

	parser.add_argument('--t_dim', type=int, default=256,
						help='Text feature dimension')

	parser.add_argument('--batch_size', type=int, default=64,
						help='Batch Size')

	parser.add_argument('--image_size', type=int, default=64,
						help='Image Size a, a x a')

	parser.add_argument('--gf_dim', type=int, default=64,
						help='Number of conv in the first layer gen.')

	parser.add_argument('--df_dim', type=int, default=64,
						help='Number of conv in the first layer discr.')

	parser.add_argument('--gfc_dim', type=int, default=1024,
						help='Dimension of gen untis for for fully connected '
							 'layer 1024')

	parser.add_argument('--caption_vector_length', type=int, default=128,
						help='Caption Vector Length')

	parser.add_argument('--data_dir', type=str, default="Data",
						help='Data Directory')

	parser.add_argument('--learning_rate', type=float, default=0.0002,
						help='Learning Rate')

	parser.add_argument('--beta1', type=float, default=0.5,
						help='Momentum for Adam Update')

	parser.add_argument('--epochs', type=int, default=200,
						help='Max number of epochs')

	parser.add_argument('--save_every', type=int, default=30,
						help='Save Model/Samples every x iterations over '
							 'batches')

	parser.add_argument('--resume_model', type=str, default=None,
						help='Pre-Trained Model Path, to resume from')

	parser.add_argument('--data_set', type=str, default="flowers",
						help='Dat set: MS-COCO, flowers')

	parser.add_argument('--model_name', type=str, default="model_1",
						help='model_1 or model_2')

	args = parser.parse_args()

	model_dir = join(args.data_dir, 'training', args.model_name)
	if not os.path.exists(model_dir):
		os.makedirs(model_dir)

	model_chkpnts_dir = join(model_dir, 'checkpoints')
	if not os.path.exists(model_chkpnts_dir):
		os.makedirs(model_chkpnts_dir)

	model_samples_dir = join(model_dir, 'samples')
	if not os.path.exists(model_samples_dir):
		os.makedirs(model_samples_dir)

	model_val_samples_dir = join(model_dir, 'val_samples')
	if not os.path.exists(model_val_samples_dir):
		os.makedirs(model_val_samples_dir)

	datasets_root_dir = join(args.data_dir, 'datasets')

	loaded_data = load_training_data(datasets_root_dir, args.data_set)
	model_options = {
		'z_dim': args.z_dim,
		't_dim': args.t_dim,
		'batch_size': args.batch_size,
		'image_size': args.image_size,
		'gf_dim': args.gf_dim,
		'df_dim': args.df_dim,
		'gfc_dim': args.gfc_dim,
		'caption_vector_length': args.caption_vector_length,
		'n_classes': loaded_data['n_classes']
	}

	gan = model.GAN(model_options)
	input_tensors, variables, loss, outputs, checks = gan.build_model()

	d_optim = tf.train.AdamOptimizer(args.learning_rate,
									 beta1=args.beta1).minimize(loss['d_loss'],
																var_list=
																variables[
																	'd_vars'])
	g_optim = tf.train.AdamOptimizer(args.learning_rate,
									 beta1=args.beta1).minimize(loss['g_loss'],
																var_list=
																variables[
																	'g_vars'])

	sess = tf.InteractiveSession()
	tf.initialize_all_variables().run()

	saver = tf.train.Saver()
	if args.resume_model:
		print('resuming model from previous checkpoint' + str(tf.train.latest_checkpoint(args.resume_model)))
		saver.restore(sess, tf.train.latest_checkpoint(args.resume_model))



	for i in range(args.epochs):
		batch_no = 0
		while batch_no * args.batch_size < loaded_data['data_length']:

			real_images, wrong_images, caption_vectors, z_noise, image_files, \
			real_classes, wrong_classes, image_caps, image_ids  = \
				get_training_batch(batch_no, args.batch_size, args.image_size,
									args.z_dim, args.caption_vector_length,
									'train', datasets_root_dir, args.data_set,
								   	loaded_data)

			# DISCR UPDATE
			check_ts = [checks['d_loss1'], checks['d_loss2'],
							checks['d_loss3']]
			_, d_loss, gen, d1, d2, d3 = sess.run(
				[d_optim, loss['d_loss'], outputs['generator']] + check_ts,
				feed_dict={
					input_tensors['t_real_image']: real_images,
					input_tensors['t_wrong_image']: wrong_images,
					input_tensors['t_real_caption']: caption_vectors,
					input_tensors['t_z']: z_noise,
					input_tensors['t_real_classes']: real_classes,
					input_tensors['t_wrong_classes']: wrong_classes
				})

			print "d1", d1
			print "d2", d2
			print "d3", d3
			print "D", d_loss

			# GEN UPDATE
			_, g_loss, gen = sess.run(
				[g_optim, loss['g_loss'], outputs['generator']],
				feed_dict={
					input_tensors['t_real_image']: real_images,
					input_tensors['t_wrong_image']: wrong_images,
					input_tensors['t_real_caption']: caption_vectors,
					input_tensors['t_z']: z_noise,
					input_tensors['t_real_classes']: real_classes,
					input_tensors['t_wrong_classes']: wrong_classes
				})

			# GEN UPDATE TWICE, to make sure d_loss does not go to 0
			_, g_loss, gen = sess.run(
				[g_optim, loss['g_loss'], outputs['generator']],
				feed_dict={
					input_tensors['t_real_image']: real_images,
					input_tensors['t_wrong_image']: wrong_images,
					input_tensors['t_real_caption']: caption_vectors,
					input_tensors['t_z']: z_noise,
					input_tensors['t_real_classes']: real_classes,
					input_tensors['t_wrong_classes']: wrong_classes
				})

			print "LOSSES", d_loss, g_loss, batch_no, i, len(
				loaded_data['image_list']) / args.batch_size
			batch_no += 1
			if (batch_no % args.save_every) == 0:
				print "Saving Images, Model"
				save_for_vis(model_samples_dir, real_images, gen, image_files, image_caps,
							 image_ids, args.image_size, args.z_dim)
				save_path = saver.save(sess,join(model_chkpnts_dir, "latest_model_{}_temp.ckpt".format(
										   args.data_set)))
				val_captions, val_z_noise, val_image_files, val_image_caps, val_image_ids = \
					get_val_caps_batch(args.batch_size, loaded_data, args.data_set, 'val', datasets_root_dir)
				for val_viz_cnt in range(0, 4):
					val_gen = sess.run(
						[outputs['generator']],
						feed_dict={
							input_tensors['t_real_caption']: val_captions,
							input_tensors['t_z']: val_z_noise
						})
					save_for_viz_val(model_val_samples_dir, val_gen, val_image_files, val_image_caps,
									 val_image_ids, args.image_size, val_viz_cnt)

		if i % 5 == 0:
			save_path = saver.save(sess, join(model_chkpnts_dir,"model_after_{}_epoch_{}.ckpt".format(
				args.data_set, i)))
			val_captions, val_z_noise, val_image_files, val_image_caps, val_image_ids = \
				get_val_caps_batch(args.batch_size, loaded_data, args.data_set, 'val', datasets_root_dir)
			for val_viz_cnt in range(0, 10):
				val_gen = sess.run(
					[outputs['generator']],
					feed_dict={
						input_tensors['t_real_caption']: val_captions,
						input_tensors['t_z']: val_z_noise
					})
				save_for_viz_val(model_val_samples_dir, val_gen, val_image_files, val_image_caps,
								 val_image_ids, args.image_size, val_viz_cnt)

def load_training_data(data_dir, data_set) :
	if data_set == 'flowers' :
		flower_captions = pickle.load(open(join(data_dir, 'flowers', 'tr_features_dict.pkl'), "rb"))
		#h1 = h5py.File(join(data_dir, 'flower_tc.hdf5'))
		img_classes = pickle.load(open(join(data_dir, 'flowers', 'flower_tc.pkl'), "rb"))

		
		n_classes = 102
		max_caps_len = 4800


		image_list = [key for key in flower_captions]
		image_list.sort()

		training_image_list = image_list
		random.shuffle(training_image_list)

		return {
			'image_list' : training_image_list,
			'captions' : flower_captions,
			'data_length' : len(training_image_list),
			'classes' : img_classes,
			'n_classes' : n_classes,
			'max_caps_len' : max_caps_len
		}

	else :
		tr_caps_features = pickle.load(
			open(os.path.join(data_dir, 'mscoco/train', 'coco_tr_tv.pkl'),
				 	"rb"))

		tr_img_classes = pickle.load(
			open(os.path.join(data_dir, 'mscoco/train', 'coco_tr_tc.pkl'),
				 "rb"))

		val_caps_features = pickle.load(
			open(os.path.join(data_dir, 'mscoco/val', 'coco_tr_tv.pkl'),
				 "rb"))

		n_classes = 80
		max_caps_len = 4800
		tr_annFile = '%s/annotations_inst/instances_%s.json' % (
								join(data_dir, 'mscoco'), 'train2014')
		tr_annFile_caps = '%s/annotations_caps/captions_%s.json' % (join(data_dir, 'mscoco'), 'train2014')

		val_annFile = '%s/annotations_inst/instances_%s.json' % (
			join(data_dir, 'mscoco'), 'val2014')
		val_annFile_caps = '%s/annotations_caps/captions_%s.json' % (join(data_dir, 'mscoco'), 'val2014')

		val_caps_coco = COCO(val_annFile)
		val_coco = COCO(val_annFile_caps)

		val_img_list = val_coco.getImgIds()
		val_n_imgs = len(val_img_list)

		tr_caps_coco = COCO(tr_annFile_caps)
		tr_coco = COCO(tr_annFile)

		tr_image_list = tr_coco.getImgIds()
		tr_n_imgs = len(tr_image_list)
		return {
			'image_list': tr_image_list,
			'captions': tr_caps_features,
			'data_length': tr_n_imgs,
			'classes': tr_img_classes,
			'n_classes': n_classes,
			'max_caps_len': max_caps_len,
			'tr_coco_obj' : tr_coco,
			'tr_coco_caps_obj' : tr_caps_coco,
			'val_coco_obj': val_coco,
			'val_coco_caps_obj': val_caps_coco,
			'val_img_list': val_img_list,
			'val_captions' : val_caps_features,
			'val_data_len' : val_n_imgs
		}

def save_for_viz_val(data_dir, generated_images, image_files, image_caps, image_ids, image_size, id):
	shutil.rmtree(data_dir)
	os.makedirs(data_dir)
	for i in range(0, generated_images.shape[0]) :
		image_dir = join(data_dir, str(image_ids[i]))
		if not os.path.exists(image_dir):
			os.makedirs(image_dir)

		real_image_path = join(image_dir,
							   '{}_{}.jpg'.format(image_ids[i], image_files[i].split('/')[-1]))
		if not os.path.exists(image_dir):
			real_images_255 = image_processing.load_image_array(image_files[i],
															image_size,
															image_ids[i])
			scipy.misc.imsave(real_image_path, real_images_255)

		caps_dir = join(image_dir, "caps.txt")
		if not os.path.exists(caps_dir):
			with open(caps_dir, "w") as text_file:
				text_file.write(image_caps[i])

		fake_images_255 = (generated_images[i, :, :, :])
		scipy.misc.imsave(join(image_dir, 'fake_image_{}.jpg'.format(id)), fake_images_255)

def save_for_vis(data_dir, real_images, generated_images, image_files, image_caps, image_ids, image_size) :
	shutil.rmtree(data_dir)
	os.makedirs(data_dir)

	for i in range(0, real_images.shape[0]) :
		real_image_255 = np.zeros((image_size, image_size, 3), dtype = np.uint8)
		real_images_255 = (real_images[i, :, :, :])
		scipy.misc.imsave(join(data_dir,
			   '{}_{}.jpg'.format(i, image_files[i].split('/')[-1])),
		                  real_images_255)

		fake_image_255 = np.zeros((image_size, image_size, 3), dtype = np.uint8)
		fake_images_255 = (generated_images[i, :, :, :])
		scipy.misc.imsave(join(data_dir, 'fake_image_{}.jpg'.format(
			i)), fake_images_255)
	str_caps = '\n'.join(image_caps)
	str_image_ids = '\n'.join(image_ids)
	with open(join(data_dir, "caps.txt"), "w") as text_file:
		text_file.write(str_caps)
	with open(join(data_dir, "ids.txt"), "w") as text_file:
		text_file.write(str_image_ids)

def get_val_caps_batch(batch_size, loaded_data, data_set, split, data_dir, z_dim):
	if data_set == 'mscoco':
		captions = np.zeros((batch_size, loaded_data['max_caps_len']))
		batch_idx = np.random.randint(0, loaded_data['val_data_len'],
									  size=batch_size)
		image_ids = np.take(loaded_data['val_img_list'], batch_idx)
		image_files = []
		image_caps = []
		for idx, image_id in enumerate(image_ids):
			image_file = join(data_dir, 'mscoco/%s2014/COCO_%s2014_%.12d.jpg' % (
				split, split, image_id))
			random_caption = random.randint(0, 4)
			captions[idx, :] = \
				loaded_data['val_captions'][image_id][random_caption][0:loaded_data['max_caps_len']]
			annIds_ = loaded_data['val_coco_caps_obj'].getAnnIds(imgIds=image_id)
			anns = loaded_data['val_coco_caps_obj'].loadAnns(annIds_)
			img_caps = [ann['caption'] for ann in anns]
			image_caps.append(img_caps[random_caption])
			image_files.append(image_file)
		z_noise = np.random.uniform(-1, 1, [batch_size, z_dim])
		return captions, z_noise, image_files, image_caps, image_ids

def get_training_batch(batch_no, batch_size, image_size, z_dim,
                       caption_vector_length, split, data_dir, data_set,
                       loaded_data = None) :
	if data_set == 'mscoco' :

		real_images = np.zeros((batch_size, image_size , image_size, 3))
		wrong_images = np.zeros((batch_size, image_size, image_size, 3))
		captions = np.zeros((batch_size, loaded_data['max_caps_len']))
		real_classes = np.zeros((batch_size, loaded_data['n_classes']))
		wrong_classes = np.zeros((batch_size, loaded_data['n_classes']))

		img_range = range(batch_no * batch_size,
						  batch_no * batch_size + batch_size)
		#batch_idx = np.random.randint(0, loaded_data['data_length'],
		#							  size=batch_size)
		image_ids = np.take(loaded_data['image_list'], img_range)
		image_files = []
		image_caps = []
		'''
		for i in range(batch_no * batch_size,
					   batch_no * batch_size + batch_size):
			idx = i % len(loaded_data['image_list'])
		'''
		for idx, image_id in enumerate(image_ids) :
			image_file = join(data_dir, 'mscoco/%s2014/COCO_%s2014_%.12d.jpg' % (
				split, split, image_id))
			image_array = image_processing.load_image_array(image_file,
			                                                	image_size,
															image_id)
			real_images[idx, :, :, :] = image_array

			random_caption = random.randint(0, 4)


			captions[idx, :] = \
				loaded_data['captions'][image_id][random_caption][0:loaded_data['max_caps_len']]

			if type(loaded_data['classes'][image_id]) == np.ndarray:
				real_classes[idx, :] = \
					loaded_data['classes'][image_id][0:loaded_data['n_classes']]
			else:
				print('case')

			annIds_ = loaded_data['tr_coco_caps_obj'].getAnnIds(imgIds=image_id)
			anns = loaded_data['tr_coco_caps_obj'].loadAnns(annIds_)
			img_caps = [ann['caption'] for ann in anns]

			image_caps.append(img_caps[random_caption])
			image_files.append(image_file)


		# TODO>> As of Now, wrong images are just shuffled real images.
		first_image = real_images[0, :, :, :]
		first_class = real_classes[0, : ]
		for i in range(0, batch_size) :
			if i < batch_size - 1 :
				wrong_images[i, :, :, :] = real_images[i + 1, :, :, :]
				wrong_classes[i, :] = real_classes[i + 1, :]
			else :
				wrong_images[i, :, :, :] = first_image
				wrong_classes[i, :] = first_class

		z_noise = np.random.uniform(-1, 1, [batch_size, z_dim])

		return real_images, wrong_images, captions, z_noise, image_files, \
			   real_classes, wrong_classes, image_caps, image_ids

	if data_set == 'flowers':
		real_images = np.zeros((batch_size, 128, 128, 3))
		wrong_images = np.zeros((batch_size, 128, 128, 3))
		#captions = np.zeros((batch_size, caption_vector_length))
		captions = np.zeros((batch_size, loaded_data['max_caps_len']))
		real_classes = np.zeros((batch_size, loaded_data['n_classes']))
		wrong_classes = np.zeros((batch_size, loaded_data['n_classes']))

		cnt = 0
		image_files = []
		for i in range(batch_no * batch_size,
		               batch_no * batch_size + batch_size) :
			idx = i % len(loaded_data['image_list'])
			image_file = join(data_dir,
			                  'flowers/jpg/' + loaded_data['image_list'][idx])
			image_array = image_processing.load_image_array_flowers(image_file,
			                                                image_size)
			real_images[cnt, :, :, :] = image_array

			# Improve this selection of wrong image
			wrong_image_id = random.randint(0,
			                                len(loaded_data['image_list']) - 1)
			wrong_image_file = join(data_dir,
			                        'flowers/jpg/' + loaded_data['image_list'][
				                                            wrong_image_id])
			wrong_image_array = image_processing.load_image_array_flowers(wrong_image_file,
			                                                      image_size)
			wrong_images[cnt, :, :, :] = wrong_image_array
			
			wrong_classes[cnt, :] = loaded_data['classes'][loaded_data['image_list'][
									wrong_image_id]][0 :loaded_data['n_classes']]

			random_caption = random.randint(0, 4)
			captions[cnt, :] = \
			loaded_data['captions'][loaded_data['image_list'][idx]][
								random_caption][0 :loaded_data['max_caps_len']]

			real_classes[cnt, :] = \
				loaded_data['classes'][loaded_data['image_list'][idx]][
												0 :loaded_data['n_classes']]
			image_files.append(image_file)
			cnt += 1
		
		z_noise = np.random.uniform(-1, 1, [batch_size, z_dim])
		return real_images, wrong_images, captions, z_noise, image_files, \
		       real_classes, wrong_classes

def tf_seq_reshape(batch_size, captions, caps_max_len):
	# Now we create batch-major vectors from the data selected above.
	batch_encoder_inputs = []

	# Batch encoder inputs are just re-indexed encoder_inputs.
	for length_idx in xrange(caps_max_len) :
		batch_encoder_inputs.append(
			np.array([[captions[batch_idx][length_idx]]
			          for batch_idx in xrange(batch_size)], dtype = np.float32))
	return batch_encoder_inputs

if __name__ == '__main__' :
	main()
