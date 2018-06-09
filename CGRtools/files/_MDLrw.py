# -*- coding: utf-8 -*-
#
#  Copyright 2017, 2018 Ramil Nugmanov <stsouko@live.ru>
#  This file is part of CGRtools.
#
#  CGRtools is free software; you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
from csv import reader
from itertools import count, chain
from ._CGRrw import CGRwrite, elements_set, fromMDL
from ..exceptions import EmptyMolecule


class MOLread:
    def __init__(self, line):
        atom_count = int(line[0:3])
        if not atom_count:
            raise EmptyMolecule('molecule without atoms')

        self.__bonds_count = int(line[3:6])
        self.__atoms_count = atom_count
        self.__props = {}
        self.__atoms = []
        self.__bonds = []

    def getvalue(self):
        if self.__mend:
            return dict(atoms=self.__atoms, bonds=self.__bonds, CGR_DAT=list(self.__props.values()), meta={}, colors={})
        raise ValueError('molecule not complete')

    def __call__(self, line):
        if len(self.__atoms) < self.__atoms_count:
            self.__atoms.append(dict(element=line[31:34].strip(), isotope=int(line[34:36]),
                                     charge=fromMDL[int(line[38:39])],
                                     map=int(line[60:63]), mark=line[54:57].strip(),
                                     x=float(line[0:10]), y=float(line[10:20]), z=float(line[20:30])))
        elif len(self.__bonds) < self.__bonds_count:
            self.__bonds.append((int(line[0:3]), int(line[3:6]), int(line[6:9]), int(line[9:12])))
        elif line.startswith("M  END"):
            self.__mend = True
            return True
        elif not self.__mend:
            self.__collect(line)
        else:
            raise SyntaxError('invalid usage')

    def __collect(self, line):
        if line.startswith('M  ALS'):
            atom = int(line[7:10])
            self.__props[('list', atom)] = dict(atoms=(atom,), type='atomlist' if line[14] == 'F' else 'atomnotlist',
                                                value=[line[16 + x*4: 20 + x*4].strip()
                                                       for x in range(int(line[10:13]))])

        elif line.startswith(('M  ISO', 'M  RAD', 'M  CHG')):
            _type = self.__ctf_data[line[3]]
            for i in range(int(line[6:9])):
                atom = int(line[10 + i * 8:13 + i * 8])
                self.__props[(_type, atom)] = dict(atoms=(atom,), type=_type, value=line[14 + i * 8:17 + i * 8].strip())

        elif line.startswith('M  STY'):
            for i in range(int(line[8])):
                if 'DAT' in line[10 + 8 * i:17 + 8 * i]:
                    self.__props[int(line[10 + 8 * i:13 + 8 * i])] = {}
        elif line.startswith('M  SAL') and int(line[7:10]) in self.__props:
            self.__props[int(line[7:10])]['atoms'] = tuple(int(line[14 + 4 * i:17 + 4 * i])
                                                           for i in range(int(line[10:13])))
        elif line.startswith('M  SDT') and int(line[7:10]) in self.__props:
            self.__props[int(line[7:10])]['type'] = line.split()[-1].lower()
        elif line.startswith('M  SED') and int(line[7:10]) in self.__props:
            self.__props[int(line[7:10])]['value'] = line[10:].strip().replace('/', '').lower()

    __ctf_data = {'R': 'radical', 'C': 'charge', 'I': 'isotope'}
    __mend = False


class EMOLread:
    def __init__(self, line):
        self.__props = []
        self.__atoms = []
        self.__bonds = []

    def getvalue(self):
        if self.__in_mol or self.__in_mol is None:
            raise ValueError('molecule not complete')
        return dict(atoms=self.__atoms, bonds=self.__bonds, CGR_DAT=self.__props, meta={}, colors={})

    def __call__(self, line):
        lineu = line.upper()
        if self.__in_mol:
            if lineu.startswith('M  V30 END CTAB'):
                if not self.__atoms:
                    raise EmptyMolecule('molecule without atoms')
                self.__in_mol = False
                return True
            elif self.__atoms_count:
                if lineu.startswith('M  V30 COUNTS'):
                    raise ValueError('invalid mol')
                elif lineu.startswith('M  V30 BEGIN ATOM'):
                    self.__current_parser = self.__atom_parser
                elif lineu.startswith('M  V30 BEGIN BOND'):
                    self.__current_parser = self.__bond_parser
                elif lineu.startswith('M  V30 BEGIN SGROUP'):
                    self.__current_parser = self.__sgroup_parser
                elif lineu.startswith('M  V30 END'):
                    x = lineu[13:].strip()
                    self.__current_parser = None

                    if x == 'ATOM':
                        if self.__current_parser == self.__atom_parser and len(self.__atoms) == self.__atoms_count:
                            return
                    elif x == 'BOND':
                        if self.__current_parser == self.__bond_parser and len(self.__bonds) == self.__bonds_count:
                            return
                    elif x == 'SGROUP':
                        if self.__current_parser == self.__sgroup_parser and len(self.__props) == self.__props_count:
                            return
                    else:
                        return
                    raise ValueError('invalid number of %s records' % x)

                elif self.__current_parser is not None:
                    collected = self.__record_collector(line)
                    if collected:
                        self.__current_parser(collected)

            elif lineu.startswith('M  V30 COUNTS'):
                a, b, s, *_ = line[13:].split()
                atom_count = int(a)
                if not atom_count:
                    raise EmptyMolecule('molecule without atoms')
                self.__bonds_count = int(b)
                self.__props_count = int(s)
                self.__atoms_count = atom_count

        elif self.__in_mol is not None:
            raise SyntaxError('invalid usage')
        elif lineu.startswith('M  V30 BEGIN CTAB'):
            self.__in_mol = True

    def __record_collector(self, line):
        if not line.endswith('-\n'):
            line = line[7:]
            if self.__current_record:
                line = self.__current_record + line
                self.__current_record = None

            return next(reader([line], delimiter=' ', quotechar='"', skipinitialspace=True))

        line = line[7:-2]
        if not self.__current_record:
            self.__current_record = line
        else:
            self.__current_record += line

    def __bond_parser(self, line):
        _, t, a1, a2, *kvs = line
        s = 0
        for kv in kvs:
            k, v = kv.split('=')
            if k.upper() == 'CFG':
                s = self.__stereo_map[v]

        self.__bonds.append((int(a1), int(a2), int(t), s))

    def __atom_parser(self, line):
        n, a, x, y, z, m, *kvs = line
        atom = int(n)

        if a.startswith('['):
            self.__props.append(dict(atoms=(atom,), type='atomlist', value=a[1:-1].split(',')))
            a = 'L'
        elif a.startswith(('NOT', 'Not', 'not')):
            a = 'L'
            self.__props.append(dict(atoms=(atom,), type='atomnotlist', value=a[5:-1].split(',')))

        r = '0'
        c = 0
        for kv in kvs:
            k, v = kv.split('=', 1)
            k = k.strip().upper()
            if not v:
                raise ValueError('invalid atom record')
            if k == 'ISIDAMARK':
                r = v
            elif k == 'CHG':
                c = int(v)
            elif k == 'MASS':
                self.__props.append(dict(atoms=(atom,), type='isotope', value=v))
            elif k == 'RAD':
                self.__props.append(dict(atoms=(atom,), type='radical', value=v))

        self.__atoms.append(dict(element=a, x=float(x), y=float(y), z=float(z), map=int(m),
                                 isotope=0, charge=c, mark=r))

    def __sgroup_parser(self, line):
        if line[1] == 'DAT':
            i = int(line[3][7:])
            if i == 1:
                atoms = (int(line[4][:-1]),)
            elif i == 2:
                atoms = (int(line[4]), int(line[5][:-1]))
            else:
                return

            res = dict(atoms=atoms)
            for kv in line[i + 4:]:
                if '=' not in kv:
                    continue
                k, v = kv.split('=', 1)
                if k == 'FIELDNAME':
                    res['type'] = v.lower()
                elif k == 'FIELDDATA':
                    res['value'] = v.lower()

            if len(res) == 3:
                self.__props.append(res)

    __current_record = __atoms_count = __in_mol = __current_parser = None
    __stereo_map = {'0': 0, '1': 1, '2': 4, '3': 6}


class MOLwrite(CGRwrite):
    @classmethod
    def _format_mol(cls, atoms, bonds, extended, cgr_dat):
        mol_prop = []
        for i in extended:
            it, iv, ia = i['type'], i['value'], i['atom']
            if it == 'isotope':
                mol_prop.append('M  ISO  1 %3d %3d\n' % (ia, iv))
            elif it == 'atomlist':
                atomslist, _type = (elements_set.difference(iv), 'T') if len(iv) > cls._half_table else (iv, 'F')
                mol_prop.append('M  ALS %3d%3d %s %s\n' % (ia, len(atomslist), _type,
                                                           ''.join('%-4s' % x for x in atomslist)))
            elif it == 'radical':
                mol_prop.append('M  RAD  1 %3d %3d\n' % (ia, iv))

        for j in count():
            sty = len(cgr_dat[j * 8:j * 8 + 8])
            if sty:
                stydat = ' '.join(['%3d DAT' % (x + j * 8) for x in range(1, 1 + sty)])
                mol_prop.append('M  STY  %d %s\n' % (sty, stydat))
            else:
                break

        for i, j in enumerate(cgr_dat, start=1):
            cx, cy = cls._get_position([atoms[x - 1] for x in j['atoms']])
            mol_prop.append('M  SAL %3d%3d %s\n' % (i, len(j['atoms']), ' '.join(['%3d' % x for x in j['atoms']])))
            mol_prop.append('M  SDT %3d %s\n' % (i, j['type']))
            mol_prop.append('M  SDD %3d %10.4f%10.4f    DAU   ALL  0       0\n' % (i, cx, cy))
            mol_prop.append('M  SED %3d %s\n' % (i, j['value']))

        return ''.join(chain(("\n  CGRtools. (c) Dr. Ramil I. Nugmanov\n"
                             "\n%3s%3s  0  0  0  0            999 V2000\n" % (len(atoms), len(bonds)),),
                             ("%(x)10.4f%(y)10.4f%(z)10.4f %(element)-3s 0%(charge)3s  0  0  0  0  0"
                              "%(mark)3s  0%(map)3s  0  0\n" % i for i in atoms),
                             ("%3d%3d%3s%3d  0  0  0\n" % i for i in bonds), mol_prop))

    _stereo_map = {-1: 6, 0: 0, 1: 1, None: 0}
    _charge_map = {-3: 7, -2: 6, -1: 5, 0: 0, 1: 3, 2: 2, 3: 1}
    _radical_map = {2: 2, 1: 1, 3: 3}