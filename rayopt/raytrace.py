# -*- coding: utf8 -*-
#
#   pyrayopt - raytracing for optical imaging systems
#   Copyright (C) 2012 Robert Jordens <jordens@phys.ethz.ch>
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Raytracing like Spencer and Murty 1962, J Opt Soc Am 52, 6
with some improvements
"""

import itertools

import numpy as np
import matplotlib.pyplot as plt

# from .special_sums import polar_sum
# from .aberration_orders import aberration_trace


def dir_to_angles(x,y,z):
    r = np.array([x,y,z], dtype=np.float64)
    return r/np.linalg.norm(r)

def tanarcsin(u):
    return u/np.sqrt(1 - u**2)

def sinarctan(u):
    return u/np.sqrt(1 + u**2)


class Trace(object):
    def __init__(self, system):
        self.system = system
        self.length = len(system)

    def print_coeffs(self, coeff, labels, sum=True):
        yield ("%2s %1s" + "% 10s" * len(labels)) % (
                ("#", "T") + tuple(labels))
        fmt = "%2s %1s" + "% 10.4g" * len(labels)
        for i, a in enumerate(coeff):
            yield fmt % ((i, self.system[i].typ) + tuple(a))
        if sum:
            yield fmt % ((" ∑", "") + tuple(coeff.sum(0)))


class ParaxialTrace(Trace):
    def __init__(self, system, aberration_orders=4):
        super(ParaxialTrace, self).__init__(system)
        self.allocate(aberration_orders)
        self.find_rays()

    def allocate(self, k):
        l = self.system.object.wavelengths
        n = self.length
        self.l = np.array([l[0], min(l), max(l)])
        self.y = np.empty((n, 2))
        self.u = np.empty((n, 2))
        self.z = np.empty(n)
        self.v = np.empty(n)
        self.n = np.empty(n)
        self.c = np.empty((n, 2, 2, k, k, k))
        self.d = np.empty_like(self.c)

    def propagate(self, start=0, stop=None):
        yu0 = np.array((self.y[0], self.u[0])).T
        n0, z = None, 0
        for i in range(start, stop or self.length):
            el = self.system[i]
            if i > 0:
                z += el.thickness
            yu, n = el.propagate_paraxial(yu0, n0, self.l)
            self.y[i], self.u[i] = yu.T
            self.n[i], self.z[i] = n, z
            self.c[i] = el.aberration(yu[:, 0], yu0[:, 1],
                    n0, n, self.c.shape[-1])
            self.v[i] = el.dispersion(self.l)
            yu0, n0 = yu, n

    def find_rays(self):
        y, u = self.y, self.u
        l = self.system.object.wavelengths
        ai = self.system.aperture_index
        m = self.system.paraxial_matrix(l, stop=ai + 1)
        mi = np.linalg.inv(m)
        r = self.system[ai].radius
        c = self.system.object.radius
        if self.system.object.finite:
            y, u, m = u, y, mi[::-1]
        y[0, 0], u[0, 0] = r*mi[0, 0] - r*mi[0, 1]*mi[1, 0]/mi[1, 1], 0
        y[0, 1], u[0, 1] = c*mi[0, 1]/mi[1, 1], c

    def __str__(self):
        t = itertools.chain(
                self.print_params(), ("",),
                self.print_trace(), ("",),
                self.print_c3(), ("",),
                #self.print_h3(), ("",),
                self.print_c5(),
                )
        return "\n".join(t)

    # TODO introduce aperture at argmax(abs(y_marginal)/radius)
    # or at argmin(abs(u_marginal))

    def size_elements(self):
        for e, y in zip(self.system[1:], self.y[1:]):
            e.radius = np.fabs(y).sum() # marginal+chief

    def focal_length_solve(self, f, i=None):
        # TODO only works for last surface
        if i is None:
            i = self.length - 2
        y0, y = self.y[(i-1, i), 0]
        u0, u = self.u[i-1, 0], -self.y[0, 0]/f
        n0, n = self.n[(i-1, i), :]
        c = (n0*u0 - n*u)/(y*(n - n0))
        self.system[i].curvature = c

    def focal_plane_solve(self):
        self.system.image.thickness -= self.y[-1, 0]/self.u[-1, 0]

    def plot(self, ax, **kwargs):
        kwargs.setdefault("linestyle", "-")
        kwargs.setdefault("color", "green")
        ax.plot(self.z, self.y[:, 0], **kwargs)
        ax.plot(self.z, self.y[:, 1], **kwargs)
        p0, p1 = self.pupil_position
        p0 += self.z[1]
        p1 += self.z[-2]
        h0, h1 = self.pupil_height
        ax.plot([p0, p0], [-h0, h0], **kwargs)
        ax.plot([p1, p1], [-h1, h1], **kwargs)

    def print_c3(self):
        c = self.c
        c = np.array([
                -2*c[:, 0, 1, 1, 0, 0],
                -c[:, 0, 1, 0, 1, 0],
                -c[:, 0, 0, 0, 1, 0],
                c[:, 0, 0, 0, 1, 0] - 2*c[:, 0, 1, 0, 0, 1],
                -2*c[:, 0, 0, 0, 0, 1],
                ])
        # transverse image seidel (like oslo)
        return self.print_coeffs(c.T*self.height[1]/2/self.lagrange,
                "SA3 CMA3 AST3 PTZ3 DIS3".split())

    def print_h3(self):
        c3a = self.aberration3*8 # chromatic
        return self.print_coeffs(c3a[(6, 12), :].T, 
                "PLC PTC".split())

    def print_c5(self):
        c = self.c + self.d
        c = np.array([
                -2*c[:, 0, 1, 2, 0, 0],
                -1*c[:, 0, 1, 1, 1, 0],
                -2*c[:, 0, 0, 1, 1, 0]-2*c[:, 0, 1, 1, 0, 1]+2*c[:, 0, 1, 0, 2, 0],
                2*c[:, 0, 1, 1, 0, 1],
                -2*c[:, 0, 0, 1, 0, 1]-2*c[:, 0, 0, 0, 2, 0]-2*c[:, 0, 1, 0, 1, 1],
                -1*c[:, 0, 1, 0, 1, 1],
                -c[:, 0, 0, 0, 1, 1]/2,
                -2*c[:, 0, 1, 0, 0, 2]+c[:, 0, 0, 0, 1, 1]/2,
                -2*c[:, 0, 0, 0, 0, 2],
                ])
        # transverse image seidel (like oslo)
        return self.print_coeffs(c.T*self.height[1]/2/self.lagrange,
                "SA5 CMA5 TOBSA5 SOBSA5 TECMA5 SECMA5 AST5 PTZ5 DIS5".split())

    def print_params(self):
        yield "lagrange: %.5g" % self.lagrange
        yield "track length: %.5g" % self.track
        yield "focal length: %.5g" % self.focal_length
        yield "object, image height: %.5g, %.5g" % self.height
        yield "front, back focal distance: %.5g, %.5g" % self.focal_distance
        yield "entry, exit pupil position: %.5g, %.5g" % self.pupil_position
        yield "entry, exit pupil height: %.5g, %.5g" % self.pupil_height
        yield "front, back numerical aperture: %.5g, %.5g" % self.numerical_aperture
        yield "front, back working f number: %.5g, %.5g" % self.f_number
        yield "front, back airy radius: %.5g, %.5g" % self.airy_radius
        yield "transverse, angular magnification: %.5g, %.5g" % self.magnification

    def print_trace(self):
        c = np.c_[self.y[:, 0], self.u[:, 0], self.y[:, 1], self.u[:, 1]]
        return self.print_coeffs(c,
                "marg y/marg u/chief y/chief u".split("/"), sum=False)
        
    @property
    def track(self):
        return self.z[-2] - self.z[1]

    @property
    def lagrange(self):
        return self.n[0]*(self.u[0,0]*self.y[0,1] - self.u[0,1]*self.y[0,0])

    @property
    def focal_length(self):
        return -self.lagrange/self.n[0]/(
                self.u[0,0]*self.u[-2,1] -
                self.u[0,1]*self.u[-2,0])

    @property
    def height(self):
        "object and image ray height"
        return self.y[0, 1], self.y[-1, 1] #self.lagrange/(self.n[-2]*self.u[-2,0])
 
    @property
    def focal_distance(self):
        "FFL and BFL from first/last surfaces"
        return -self.y[1,0]/self.u[0,0], -self.y[-2,0]/self.u[-2,0]
       
    @property
    def numerical_aperture(self):
        return (abs(self.n[0]*sinarctan(self.u[0,0])),
                abs(self.n[-2]*sinarctan(self.u[-2,0])))

    @property
    def pupil_position(self):
        return -self.y[1,1]/self.u[0,1], -self.y[-2,1]/self.u[-2,1]

    @property
    def pupil_height(self):
        p0, p1 = self.pupil_position
        return self.y[1,0] + p0*self.u[0,0], self.y[-2,0] + p1*self.u[-2,0]

    @property
    def f_number(self):
        na0, na1 = self.numerical_aperture
        return 1/(2*na0), 1/(2*na1)

    @property
    def airy_radius(self):
        na0, na1 = self.numerical_aperture
        return 1.22*self.l[0]/(2*na0), 1.22*self.l[0]/(2*na1)

    @property
    def magnification(self):
        return ((self.n[0]*self.u[0,0])/(self.n[-2]*self.u[-2,0]),
                (self.n[-2]*self.u[-2,1])/(self.n[1]*self.u[0,1]))


class FullTrace(Trace):
    def __init__(self, system, nrays):
        super(FullTrace, self).__init__(system)
        self.allocate(nrays)

    def allocate(self, nrays):
        self.nrays = nrays
        self.y = np.empty((self.length, nrays, 3))
        self.u = np.empty_like(self.y)
        self.l = np.empty(nrays)
        self.z = np.empty(self.length)
        self.n = np.empty((self.length, nrays))
        self.t = np.empty_like(self.n)

    def propagate(self, clip=True):
        y, u, n, l, z = self.y[0], self.u[0], None, self.l, 0
        for i, e in enumerate(self.system):
            y, u, n, t = e.transformed_yu(e.propagate, y, u, n, l, clip)
            self.y[i], self.u[i], self.n[i], self.t[i] = (y, u, n, t)
            self.z[i] = z = z + e.thickness

    def plot(self, ax, axis=0, **kwargs):
        kwargs.setdefault("linestyle", "-")
        kwargs.setdefault("color", "green")
        kwargs.setdefault("alpha", .3)
        y = self.y[:, :, 0]
        z = self.y[:, :, 2] + self.z[:, None]
        ax.plot(z, y, **kwargs)

    @classmethod
    def like_paraxial(cls, paraxial):
        obj = cls(paraxial.system, 2)
        obj.rays_like_paraxial(paraxial)
        return obj

    def rays_like_paraxial(self, paraxial):
        self.l[:] = self.system.object.wavelengths[0]
        self.y[0, :, :] = 0
        self.y[0, :, 0] = paraxial.y[0]
        self.u[0, :, :] = 0
        self.u[0, :, 0] = sinarctan(paraxial.u[0])
        self.u[0, :, 2] = np.sqrt(1 - self.u[0, :, 0]**2)

    def rays_for_point(self, paraxial, height, wavelength, nrays,
            distribution):
        # TODO apodization
        xp, yp = self.get_rays(distribution, nrays)
        hp, rp = paraxial.pupil_position[0], paraxial.pupil_height[0]
        r = self.system.object.radius
        if not self.system.object.finite:
            r = sinarctan(r)
            p, q = height[0]*r, height[1]*r
            a, b = xp*rp-hp*tanarcsin(p), yp*rp-hp*tanarcsin(q)
        else:
            a, b = height[0]*r, height[1]*r
            p, q = sinarctan((xp*rp-a)/hp), sinarctan((yp*rp-b)/hp)
        self.allocate(xp.shape[0])
        self.l[:] = wavelength
        self.n[0] = self.system.object.material.refractive_index(
                wavelength)
        self.y[0] = np.array((a, b, np.zeros_like(a))).T
        self.u[0] = np.array((p, q, np.sqrt(1 - p**2 - q**2))).T

    def rays_for_object(self, paraxial, wavelength, nrays, eps=1e-6):
        hp, rp = paraxial.pupil_position[0], paraxial.pupil_height[0]
        r = self.system.object.radius
        if self.system.object.infinity:
            r = sinarctan(r)
        xi, yi = np.tile([np.linspace(0, r, nrays), np.zeros((nrays,),
            dtype=np.float64)], 3)
        xp, yp = np.zeros_like(xi), np.zeros_like(yi)
        xp[nrays:2*nrays] = eps*rp
        yp[2*nrays:] = eps*rp
        if self.system.object.infinity:
            p, q = xi, yi
            a, b = xp-hp*tanarcsin(p), yp-hp*tanarcsin(q)
        else:
            a, b = xi, yi
            p, q = sinarctan((xp-a)/hp), sinarctan((yp-b)/hp)
        self.nrays = nrays*3
        self.allocate()
        self.l[:] = wavelength
        self.n[0] = self.system.object.material.refractive_index(
                wavelength)
        self.y[0, 0] = a
        self.y[1, 0] = b
        self.y[2, 0] = 0
        self.u[0, 0] = p
        self.u[1, 0] = q
        self.u[2, 0] = np.sqrt(1-p**2-q**2)

    def plot_transverse(self, heights, wavelengths, fig=None, paraxial=None,
            npoints_spot=100, npoints_line=30):
        if fig is None:
            fig = plt.figure(figsize=(10, 8))
            fig.subplotpars.left = .05
            fig.subplotpars.bottom = .05
            fig.subplotpars.right = .95
            fig.subplotpars.top = .95
            fig.subplotpars.hspace = .2
            fig.subplotpars.wspace = .2
        if paraxial is None:
            paraxial = ParaxialTrace(system=self.system)
            paraxial.propagate()
        nh = len(heights)
        ia = self.system.aperture_index
        n = npoints_line
        gs = plt.GridSpec(nh, 6)
        axm0, axs0, axl0, axc0 = None, None, None, None
        for i, hi in enumerate(heights):
            axm = fig.add_subplot(gs.new_subplotspec((i, 0), 1, 2),
                    sharex=axm0, sharey=axm0)
            if axm0 is None: axm0 = axm
            #axm.set_title("meridional h=%s, %s" % hi)
            #axm.set_xlabel("Y")
            #axm.set_ylabel("tanU")
            axs = fig.add_subplot(gs.new_subplotspec((i, 2), 1, 1),
                    sharex=axs0, sharey=axs0)
            if axs0 is None: axs0 = axs
            #axs.set_title("sagittal h=%s, %s" % hi)
            #axs.set_xlabel("X")
            #axs.set_ylabel("tanV")
            axl = fig.add_subplot(gs.new_subplotspec((i, 3), 1, 1),
                    sharex=axl0, sharey=axl0)
            if axl0 is None: axl0 = axl
            #axl.set_title("longitudinal h=%s, %s" % hi)
            #axl.set_xlabel("Z")
            #axl.set_ylabel("H")
            axp = fig.add_subplot(gs.new_subplotspec((i, 4), 1, 1),
                    aspect="equal", sharex=axs0, sharey=axm0)
            #axp.set_title("rays h=%s, %s" % hi)
            #axp.set_ylabel("X")
            #axp.set_ylabel("Y")
            axc = fig.add_subplot(gs.new_subplotspec((i, 5), 1, 1),
                    sharex=axc0, sharey=axc0)
            if axc0 is None: axc0 = axc
            #axc.set_title("encircled h=%s, %s" % hi)
            #axc.set_ylabel("R")
            #axc.set_ylabel("E")
            for j, wi in enumerate(wavelengths):
                self.rays_for_point(paraxial, hi, wi, npoints_line, "tee")
                self.propagate()
                # top rays (small tanU) are right/top
                axm.plot(-tanarcsin(self.u[0, -1, :2*n/3])
                        +tanarcsin(paraxial.u[0, -1, 1])*hi[0],
                        self.y[0, -1, :2*n/3]-paraxial.y[0, -1, 1]*hi[0],
                        "-", label="%s" % wi)
                axs.plot(self.y[1, -1, 2*n/3:],
                        -tanarcsin(self.u[1, -1, 2*n/3:]),
                        "-", label="%s" % wi)
                axl.plot(-(self.y[0, -1, :2*n/3]-paraxial.y[0, -1, 1]*hi[0])*
                        self.u[2, -1, :2*n/3]/self.u[0, -1, :2*n/3],
                        self.y[0, ia, :2*n/3],
                        "-", label="%s" % wi)
                self.rays_for_point(paraxial, hi, wi, npoints_spot,
                        "random")
                self.propagate()
                axp.plot(self.y[1, -1]-paraxial.y[0, -1, 1]*hi[1],
                        self.y[0, -1]-paraxial.y[0, -1, 1]*hi[0],
                        ".", markersize=3, markeredgewidth=0,
                        label="%s" % wi)
                xy = self.y[(0, 1), -1]
                xy = xy[:, np.all(np.isfinite(xy), 0)]
                xym = xy.mean(axis=1)
                r = ((xy-xym[:, None])**2).sum(axis=0)**.5
                rb = np.bincount(
                        (r*(npoints_line/r.max())).astype(np.int),
                        minlength=npoints_line+1).cumsum()
                axc.plot(np.linspace(0, r.max(), npoints_line+1),
                        rb.astype(np.float)/self.y.shape[2])
            for ax in axs0, axm0, axc0:
                ax.relim()
                ax.autoscale_view(True, True, True)
        return fig

    def plot_longitudinal(self, wavelengths, fig=None, paraxial=None,
            npoints=20):
        if fig is None:
            fig = plt.figure(figsize=(6, 4))
            fig.subplotpars.left = .05
            fig.subplotpars.bottom = .05
            fig.subplotpars.right = .95
            fig.subplotpars.top = .95
            fig.subplotpars.hspace = .2
            fig.subplotpars.wspace = .2
        if paraxial is None:
            paraxial = ParaxialTrace(system=self.system)
            paraxial.propagate()
        n = npoints
        gs = plt.GridSpec(1, 2)
        axl = fig.add_subplot(gs.new_subplotspec((0, 0), 1, 1))
        #axl.set_title("distortion")
        #axl.set_xlabel("D")
        #axl.set_ylabel("Y")
        axc = fig.add_subplot(gs.new_subplotspec((0, 1), 1, 1))
        #axl.set_title("field curvature")
        #axl.set_xlabel("Z")
        #axl.set_ylabel("Y")
        for i, (wi, ci) in enumerate(zip(wavelengths, "bgrcmyk")):
            self.rays_for_object(paraxial, wi, npoints)
            self.propagate()
            axl.plot(self.y[0, -1, :npoints]-np.linspace(0, paraxial.height[1], npoints),
                self.y[0, -1, :npoints], ci+"-", label="d")
            # tangential field curvature
            # -(real_y-parax_y)/(tanarcsin(real_u)-tanarcsin(parax_u))
            xt = -(self.y[0, -1, npoints:2*npoints]-self.y[0, -1, :npoints])/(
                  tanarcsin(self.u[0, -1, npoints:2*npoints])-tanarcsin(self.u[0, -1, :npoints]))
            # sagittal field curvature
            # -(real_x-parax_x)/(tanarcsin(real_v)-tanarcsin(parax_v))
            xs = -(self.y[1, -1, 2*npoints:]-self.y[1, -1, :npoints])/(
                  tanarcsin(self.u[1, -1, 2*npoints:])-tanarcsin(self.u[1, -1, :npoints]))
            axc.plot(xt, self.y[0, -1, :npoints], ci+"--", label="zt")
            axc.plot(xs, self.y[0, -1, :npoints], ci+"-", label="zs")
        return fig

    def get_rays(self, distribution, nrays):
        d = distribution
        n = nrays
        if d == "random":
            xy = 2*np.random.rand(2, n*4/np.pi)-1
            return xy[:, (xy**2).sum(0)<=1]
        elif d == "meridional":
            return np.linspace(-1, 1, n), np.zeros((n,))
        elif d == "sagittal":
            return np.zeros((n,)), np.linspace(-1, 1, n)
        elif d == "square":
            r = np.around(np.sqrt(n*4/np.pi))
            x, y = np.mgrid[-1:1:1j*r, -1:1:1j*r]
            xy = np.array([x.ravel(), y.ravel()])
            return xy[:, (xy**2).sum(0)<=1]
        elif d == "triangular":
            r = np.around(np.sqrt(n*4/np.pi))
            x, y = np.mgrid[-1:1:1j*r, -1:1:1j*r]
            xy = np.array([x.ravel(), y.ravel()])
            return xy[:, (xy**2).sum(0)<=1]
        elif d == "hexapolar":
            r = int(np.around(np.sqrt(n/3.-1/12.)-1/2.))
            l = [[np.array([0]), np.array([0])]]
            for i in range(1, r+1):
                a = np.arange(0, 2*np.pi, 2*np.pi/(6*i))
                l.append([i*np.sin(a)/r, i*np.cos(a)/r])
            return np.concatenate(l, axis=1)
        elif d == "cross":
            return np.concatenate([
                [np.linspace(-1, 1, n/2), np.zeros((n/2,))],
                [np.zeros((n/2,)), np.linspace(-1, 1, n/2)]], axis=1)
        elif d == "tee":
            return np.concatenate([
                [np.linspace(-1, 1, 2*n/3), np.zeros((2*n/3,))],
                [np.zeros((n/3,)), np.linspace(0, 1, n/3)]], axis=1)

    def __str__(self):
        t = itertools.chain(
                #self.print_params(),
                self.print_trace(),
                #self.print_c3(),
                )
        return "\n".join(t)

    def print_trace(self):
        for i in range(self.nrays):
            yield "ray %i, %.3g nm" % (i, self.l[i]/1e-9)
            c = np.concatenate((self.n[:, i, None], self.z[:, None],
                np.cumsum(self.t[:, i, None], axis=0),
                self.y[:, i, :], self.u[:, i, :]), axis=1)
            for _ in self.print_coeffs(c, "n/track z/path len/"
                    "height x/height y/height z/angle x/angle y/angle z"
                    .split("/"), sum=False):
                yield _
            yield ""

