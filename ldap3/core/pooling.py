"""
"""

# Created on 2014.03.14
#
# Author: Giovanni Cannata
#
# Copyright 2015 Giovanni Cannata
#
# This file is part of ldap3.
#
# ldap3 is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ldap3 is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with ldap3 in the COPYING and COPYING.LESSER files.
# If not, see <http://www.gnu.org/licenses/>.

from datetime import datetime
from os import linesep
from random import randint

from .. import FIRST, ROUND_ROBIN, RANDOM, POOLING_STRATEGIES, SEQUENCE_TYPES, STRING_TYPES
from .exceptions import LDAPUnknownStrategyError, LDAPServerPoolError, LDAPServerPoolExhaustedError
from .server import Server
from ..utils.log import log, log_enabled, VERBOSITY_ERROR, VERBOSITY_BASIC


class ServerPoolState(object):
    def __init__(self, server_pool):
        self.servers = []
        self.strategy = server_pool.strategy
        self.server_pool = server_pool
        self.refresh()
        self.initialize_time = datetime.now()
        self.last_used_server = randint(0, len(self.servers) - 1)

        if log_enabled(VERBOSITY_BASIC):
            log(VERBOSITY_BASIC, 'instantiated ServerPoolState: <%r>', self)

    def __str__(self):
        s = 'servers: ' + linesep
        if self.servers:
            for server in self.servers:
                s += str(server) + linesep
        else:
            s += 'None' + linesep
        s += 'Pool strategy: ' + str(self.strategy) + linesep
        s += ' - Last used server: ' + ('None' if self.last_used_server == -1 else str(self.servers[self.last_used_server]))

        return s

    def refresh(self):
        self.servers = []
        for server in self.server_pool.servers:
            self.servers.append(server)
        self.last_used_server = randint(0, len(self.servers) - 1)

    def get_current_server(self):
        return self.servers[self.last_used_server]

    def get_server(self):
        if self.servers:
            if self.server_pool.strategy == FIRST:
                if self.server_pool.active:
                    # returns the first active server
                    self.last_used_server = self.find_active_server(starting=0, exhaust=self.server_pool.exhaust)
                else:
                    # returns always the first server - no pooling
                    self.last_used_server = 0
            elif self.server_pool.strategy == ROUND_ROBIN:
                if self.server_pool.active:
                    # returns the next active server in a circular range
                    self.last_used_server = self.find_active_server(self.last_used_server + 1, exhaust=self.server_pool.exhaust)
                else:
                    # returns the next server in a circular range
                    self.last_used_server = self.last_used_server + 1 if (self.last_used_server + 1) < len(self.servers) else 0
            elif self.server_pool.strategy == RANDOM:
                if self.server_pool.active:
                    self.last_used_server = self.find_active_random_server(exhaust=self.server_pool.exhaust)
                else:
                    # returns a random server in the pool
                    self.last_used_server = randint(0, len(self.servers))
            else:
                if log_enabled(VERBOSITY_ERROR):
                    log(VERBOSITY_ERROR, 'unknown server pooling strategy <%s>', self.server_pool.strategy)
                raise LDAPUnknownStrategyError('unknown server pooling strategy')
            if log_enabled(VERBOSITY_BASIC):
                log(VERBOSITY_BASIC, 'server returned from Server Pool: <%s>', self.last_used_server)
            return self.servers[self.last_used_server]
        else:
            if log_enabled(VERBOSITY_ERROR):
                log(VERBOSITY_ERROR, 'no servers in Server Pool <%s>', self)
            raise LDAPServerPoolError('no servers in server pool')

    def find_active_random_server(self, exhaust=True):
        while True:
            temp_list = self.servers[:]  # copy
            while temp_list:
                # pops a random server from a temp list and checks its
                # availability, if not available tries another one
                server = temp_list.pop(randint(0, len(temp_list) - 1))
                if server.check_availability():
                    # returns a random active server in the pool
                    return self.servers.index(server)
            if exhaust:
                if log_enabled(VERBOSITY_ERROR):
                    log(VERBOSITY_ERROR, 'no random active server in Server Pool <%s>', self)
                raise LDAPServerPoolExhaustedError('no random active server in server pool')

    def find_active_server(self, starting=0, exhaust=True):
        while True:
            index = starting
            while index < len(self.servers):
                if self.servers[index].check_availability():
                    break
                index += 1
            else:
                # if no server found in the list (from starting index)
                # checks starting from the base of the list
                index = 0
                while index < starting:
                    if self.servers[index].check_availability():
                        break
                    index += 1
                else:
                    if exhaust:
                        if log_enabled(VERBOSITY_ERROR):
                            log(VERBOSITY_ERROR, 'no active server available in Server Pool <%s>', self)
                        raise LDAPServerPoolExhaustedError('no active server available in server pool')
                    else:
                        continue
            return index

    def __len__(self):
        return len(self.servers)


class ServerPool(object):
    def __init__(self,
                 servers=None,
                 pool_strategy=ROUND_ROBIN,
                 active=True,
                 exhaust=False):

        if pool_strategy not in POOLING_STRATEGIES:
            if log_enabled(VERBOSITY_ERROR):
                log(VERBOSITY_ERROR, 'unknown pooling strategy <%s>', pool_strategy)
            raise LDAPUnknownStrategyError('unknown pooling strategy')
        if exhaust and not active:
            if log_enabled(VERBOSITY_ERROR):
                log(VERBOSITY_ERROR, 'cannot instantiate pool with exhaust and not active')
            raise LDAPServerPoolError('pools can be exhausted only when checking for active servers')
        self.servers = []
        self.pool_states = dict()
        self.active = active
        self.exhaust = exhaust
        if isinstance(servers, SEQUENCE_TYPES + (Server, )):
            self.add(servers)
        elif isinstance(servers, STRING_TYPES):
            self.add(Server(servers))
        self.strategy = pool_strategy

        if log_enabled(VERBOSITY_BASIC):
            log(VERBOSITY_BASIC, 'instantiated ServerPool: <%r>', self)

    def __str__(self):
            s = 'servers: ' + linesep
            if self.servers:
                for server in self.servers:
                    s += str(server) + linesep
            else:
                s += 'None' + linesep
            s += 'Pool strategy: ' + str(self.strategy)
            s += ' - ' + 'active only: ' + ('True' if self.active else 'False')
            s += ' - ' + 'exhaust pool: ' + ('True' if self.exhaust else 'False')
            return s

    def __repr__(self):
        r = 'ServerPool(servers='
        if self.servers:
            r += '['
            for server in self.servers:
                r += server.__repr__() + ', '
            r = r[:-2] + ']'
        else:
            r += 'None'
        r += ', pool_strategy={0.strategy!r}'.format(self)
        r += ', active={0.active!r}'.format(self)
        r += ', exhaust={0.exhaust!r}'.format(self)
        r += ')'

        return r

    def __len__(self):
        return len(self.servers)

    def __getitem__(self, item):
        return self.servers[item]

    def __iter__(self):
        return self.servers.__iter__()

    def add(self, servers):
        if isinstance(servers, Server):
            if servers not in self.servers:
                self.servers.append(servers)
        elif isinstance(servers, STRING_TYPES):
            self.servers.append(Server(servers))
        elif isinstance(servers, SEQUENCE_TYPES):
            for server in servers:
                if isinstance(server, Server):
                    self.servers.append(server)
                elif isinstance(server, STRING_TYPES):
                    self.servers.append(Server(server))
                else:
                    if log_enabled(VERBOSITY_ERROR):
                        log(VERBOSITY_ERROR, 'element must be a server in Server Pool <%s>', self)
                    raise LDAPServerPoolError('server in ServerPool must be a Server')
        else:
            if log_enabled(VERBOSITY_ERROR):
                log(VERBOSITY_ERROR, 'server must be a Server of a list of Servers when adding to Server Pool <%s>', self)
            raise LDAPServerPoolError('server must be a Server or a list of Server')

        for connection in self.pool_states:
            # notifies connections using this pool to refresh
            self.pool_states[connection].refresh()

    def remove(self, server):
        if server in self.servers:
            self.servers.remove(server)
        else:
            if log_enabled(VERBOSITY_ERROR):
                log(VERBOSITY_ERROR, 'server %s to be removed not in Server Pool <%s>', server, self)
            raise LDAPServerPoolError('server not in server pool')

        for connection in self.pool_states:
            # notifies connections using this pool to refresh
            self.pool_states[connection].refresh()

    def initialize(self, connection):
        pool_state = ServerPoolState(self)
        # registers pool_state in ServerPool object
        self.pool_states[connection] = pool_state

    def get_server(self, connection):
        if connection in self.pool_states:
            return self.pool_states[connection].get_server()
        else:
            if log_enabled(VERBOSITY_ERROR):
                log(VERBOSITY_ERROR, 'connection <%s> not in Server Pool State <%s>', connection, self)
            raise LDAPServerPoolError('connection not in ServerPoolState')

    def get_current_server(self, connection):
        if connection in self.pool_states:
            return self.pool_states[connection].get_current_server()
        else:
            if log_enabled(VERBOSITY_ERROR):
                log(VERBOSITY_ERROR, 'connection <%s> not in Server Pool State <%s>', connection, self)
            raise LDAPServerPoolError('connection not in ServerPoolState')
