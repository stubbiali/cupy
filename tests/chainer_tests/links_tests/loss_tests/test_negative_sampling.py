import unittest

import numpy

import chainer
from chainer import cuda
from chainer.functions.loss import negative_sampling
from chainer import gradient_check
from chainer import links
from chainer import testing
from chainer.testing import attr
from chainer.testing import condition


class TestNegativeSampling(unittest.TestCase):
    def setUp(self):
        self.link = links.NegativeSampling(3, [10, 5, 2, 5, 2], 2)
        self.link.zerograds()
        self.x = numpy.random.uniform(-1, 1, (2, 3)).astype(numpy.float32)
        self.t = numpy.array([0, 2]).astype(numpy.int32)
        self.gy = numpy.random.uniform(-1, 1, ()).astype(numpy.float32)

    def check_backward(self, x_data, t_data, y_grad, use_cudnn=True):
        x = chainer.Variable(x_data)
        t = chainer.Variable(t_data)
        W = self.link.W

        y = self.link(x, t)
        y.grad = y_grad
        y.backward()

        # fix samples
        negative_sampling.NegativeSamplingFunction.samples = y.creator.samples

        def f():
            return (self.link(x, t).data,)
        gx, gW = gradient_check.numerical_grad(
            f, (x.data, W.data), (y.grad,), eps=1e-2)
        del negative_sampling.NegativeSamplingFunction.samples  # clean up

        gradient_check.assert_allclose(
            cuda.to_cpu(gx), cuda.to_cpu(x.grad), atol=1.e-4)
        gradient_check.assert_allclose(
            cuda.to_cpu(gW), cuda.to_cpu(W.grad), atol=1.e-4)
        return x.grad, W.grad

    @attr.gpu
    @condition.retry(3)
    def test_forward_gpu(self):
        x = chainer.Variable(self.x)
        t = chainer.Variable(self.t)
        y = self.link(x, t)

        self.assertEqual(y.data.dtype, numpy.float32)
        self.assertEqual(y.data.shape, ())

        # fix samples
        negative_sampling.NegativeSamplingFunction.samples = cuda.to_gpu(
            y.creator.samples)
        self.link.to_gpu()
        y_g = self.link(chainer.Variable(cuda.to_gpu(self.x)),
                        chainer.Variable(cuda.to_gpu(self.t)))
        del negative_sampling.NegativeSamplingFunction.samples

        self.assertEqual(y_g.data.dtype, numpy.float32)
        self.assertEqual(y_g.data.shape, ())

        gradient_check.assert_allclose(y.data, y_g.data, atol=1.e-4)
        return y.data, y_g.data

    @condition.retry(3)
    def test_backward_cpu(self):
        self.check_backward(self.x, self.t, self.gy)

    @attr.gpu
    @condition.retry(3)
    def test_backward_gpu(self):
        self.link.to_gpu()
        self.check_backward(cuda.to_gpu(self.x),
                            cuda.to_gpu(self.t),
                            cuda.to_gpu(self.gy))

    @attr.gpu
    def test_to_cpu(self):
        self.link.to_gpu()
        self.assertTrue(self.link.sampler.use_gpu)
        self.link.to_cpu()
        self.assertFalse(self.link.sampler.use_gpu)

    @attr.gpu
    def test_backward_cpu_gpu(self):
        x = chainer.Variable(self.x)
        t = chainer.Variable(self.t)
        y = self.link(x, t)
        y.backward()

        # fix samples
        negative_sampling.NegativeSamplingFunction.samples = cuda.to_gpu(
            y.creator.samples)
        self.link.to_gpu()
        del negative_sampling.NegativeSamplingFunction.samples
        xg = chainer.Variable(cuda.to_gpu(self.x))
        tg = chainer.Variable(cuda.to_gpu(self.t))
        y_g = self.link(xg, tg)
        y_g.backward()

        gradient_check.assert_allclose(x.grad, xg.grad, atol=1.e-4)


class TestNegativeSamplingIgnoreMask(TestNegativeSampling):

    def setUp(self):
        # Create two identical datasets except that 2nd dataset has the
        # negative targets explicitly removed. Both cases should have identical
        # outcomes.
        self.link = links.NegativeSampling(3, [10, 5, 2, 5, 2], 2)
        self.link.zerograds()
        self.x = numpy.random.uniform(-1, 1, (3, 3)).astype(numpy.float32)
        self.t = numpy.array([-1, 1, 2]).astype(numpy.int32)
        self.gy = numpy.random.uniform(-1, 1, ()).astype(numpy.float32)
        self.idx = self.t > -1
        self.x0 = self.x.copy()[self.idx]
        self.t0 = self.t.copy()[self.idx]
        self.gy0 = self.gy.copy()

    def test_ignore_forward(self):
        # Ensure that the loss when an ignore target is included is the same
        # as when it is excluded explicitly.
        x = chainer.Variable(self.link.xp.asarray(self.x))
        t = chainer.Variable(self.link.xp.asarray(self.t))
        y = self.link(x, t)
        x0 = chainer.Variable(self.link.xp.asarray(self.x0))
        t0 = chainer.Variable(self.link.xp.asarray(self.t0))
        y0 = self.link(x0, t0)
        gradient_check.assert_allclose(y.data, y0.data, atol=1.e-4)

    @attr.gpu
    def test_ignore_forward_gpu(self):
        self.link.to_gpu()
        self.test_ignore_forward()

    def test_ignore_backward(self):
        # Ensure that the gradient when an ignore target is included is the
        # same as when it is excluded explicitly.
        gx, gw = self.check_backward(
            self.link.xp.asarray(self.x),
            self.link.xp.asarray(self.t),
            self.link.xp.asarray(self.gy))
        self.link.zerograds()
        gx0, gw0 = self.check_backward(
            self.link.xp.asarray(self.x0),
            self.link.xp.asarray(self.t0),
            self.link.xp.asarray(self.gy0))
        gradient_check.assert_allclose(
            cuda.to_cpu(gx)[self.idx, :], gx0, atol=1.e-4)
        gradient_check.assert_allclose(gw, gw0, atol=1.e-4)

    @attr.gpu
    def test_ignore_backward_gpu(self):
        self.link.to_gpu()
        self.test_ignore_backward()


testing.run_module(__name__, __file__)
