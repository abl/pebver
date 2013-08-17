import gevent.monkey; gevent.monkey.patch_all()
import bottle
from bottle import run, request, response, post, get, install
import os, sys
import logging
import urllib2, requests
from collections import OrderedDict

log = logging.getLogger()
logging.basicConfig(format='[%(levelname)-8s] %(message)s')
log.setLevel(logging.DEBUG)

from iron_cache import *
cache = IronCache()

def fetch_version(owner, repository, branch='master'):
    key=":".join([owner, repository, branch])
    try:
        (major, minor) = (int(x) for x in cache.get(cache="version_cache", key=key).value.split(","))
    except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError):
        URI = 'https://raw.github.com/%s/%s/%s/src/version.h' % (owner, repository, branch)
        try:
            version = urllib2.urlopen(URI)
        except:
            return (0,0)
        
        major = None
        minor = None
        
        for line in version:
            p = line.strip().split(" ", 2)
            if p[0] == "#define":
                if p[1] == "MAJOR_VERSION":
                    major = int(p[2])
                elif p[1] == "MINOR_VERSION":
                    minor = int(p[2])
                if major is not None and minor is not None:
                    break

        if major is None:
            major = 0
        if minor is None:
            minor = 0
        
        cache.put(cache="version_cache", key=key, options={"expires_in":3600},
                  value = "%s,%s" % (major, minor))
    
    return (major, minor)

class PebbleJSONEncoder(json.JSONEncoder):
     def default(self, obj):
         if isinstance(obj, PebbleValue):
             return obj.asJson()
         # Let the base class default method raise the TypeError
         return json.JSONEncoder.default(self, obj)

json_dumps = json.dumps
class PebbleJSONPlugin(object):
    name = 'pebblejson'
    api  = 2

    def __init__(self, json_dumps=json_dumps):
        self.json_dumps = json_dumps

    def apply(self, callback, route):
        dumps = self.json_dumps
        if not dumps: return callback
        def wrapper(*a, **ka):
            rv = callback(*a, **ka)
            if isinstance(rv, dict):
                pebbleId = request.headers.get('X-Pebble-ID', None)
                accept = request.headers.get('Accept', 'application/vnd.httpebble.named+json')
                r = OrderedDict()
                if pebbleId or accept == 'application/vnd.httpebble.raw+json':
                    i = 1
                    for k in rv:
                        r[str(i)] = rv[k]
                        i+= 1
                    if pebbleId:
                        accept = 'application/json'
                elif accept == 'application/json':
                    r = rv
                else:
                    accept = 'application/vnd.httpebble.named+json'
                    i = 1
                    for k in rv:
                        r[i] = OrderedDict()
                        r[i]['name'] = k
                        r[i]['value'] = rv[k]
                        i += 1
                    
                #Attempt to serialize, raises exception on failure
                json_response = dumps(r, cls=PebbleJSONEncoder)
                #Set content type only if serialization succesful
                response.content_type = accept
                return json_response
            return rv
        return wrapper

class PebbleValue(object):
    pass

class PebbleInteger(PebbleValue):
    WIDTHS = {
        1:'b',
        2:'s',
        4:'i'
    }

    def asJson(self):
        format = PebbleInteger.WIDTHS[self._width]
        if self._unsigned:
            format = format.upper()
        
        return [format, self._value]

    def __init__(self, value, width, unsigned=True):
        self._value = value
        self._width = width
        self._unsigned = unsigned

def pebbleize(function):
    def inner():
        pebbleId = request.headers.get('X-Pebble-ID')
        data = request.json
        argc = function.func_code.co_argcount-1 #ID is always the first parameter
        name = function.func_code.co_name
        if data is None:
            log.error("Invalid request data - couldn't get JSON")
            return None #TODO: Error codes.
        if len(data) != argc:
            log.error("Argument count mismatch calling %s - expected %d got %d" % (name, argc, len(data)))
            return None #TODO: Come up with a reasonable error code return mechanism.
        args = []
        for key in xrange(argc):
            k = str(key+1)
            args.append(data[k])
        array = function(pebbleId, *args)

        output = {}
        total = 0
        i = 0
        while len(array):
            i+=1
            v = array.pop(0)
            output[str(i)] = v

        return output

    return inner

def gitsafe(s):
    return "".join(x for x in s if x.isalnum() or x == "-")

@get('/github/<owner>/<repository>/<branch>')
@get('/github/<owner>/<repository>')
def get_version(owner, repository, branch='master'):
    owner = gitsafe(owner)
    repository = gitsafe(repository)
    branch = gitsafe(branch)
    v = fetch_version(owner, repository, branch)
    return OrderedDict([('major',PebbleInteger(v[0], 1)),('minor',PebbleInteger(v[1], 1))])

@post('/github')
def post_version():
    id = request.headers.get('X-Pebble-ID')

if __name__=="__main__":
    bottle.debug(True)
    install(PebbleJSONPlugin())
    run(server='gevent', host='0.0.0.0', port=os.environ.get('PORT', 5000), autojson=True)
