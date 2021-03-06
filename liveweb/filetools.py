from cStringIO import StringIO
import httplib
import tempfile
import logging
import os

from . import config

class SizeLimitExceeded(IOError): pass


def spy(fileobj, spyobj = None, max_size = None):
    """Returns a new file wrapper the records the contents of a file
    as someone is reading from it.
    """
    return SpyFile(fileobj, spyobj, max_size)

class SpyFile:
    """File wrapper to record the contents of a file as someone is
    reading from it.

    If the "spy" parameter is passed, it will be the stream to which
    the read data is written.

    SpyFile works like a "tee"
                          
                        -------------
     Actual client <--- SpyFileObject <--- Data Source
                        ____     ____
                            \ | /    
                              |      
                              V      
                             spy     
                         (spy object) 
    
                              
    """
    def _check_size(self):
        """Raises SizeLimitExceeded if the SpyFile has seen more data
        than the specified limit"""
        if self.max_size:
            if self.current_size > int(self.max_size):
                raise SizeLimitExceeded("Spy file limit exceeded %d (max size : %d)"%(self.current_size, self.max_size))

    def __init__(self, fileobj, spy = None, max_size = None):
        self.fileobj = fileobj
        self.buf = spy or StringIO()
        self.max_size = max_size
        self.current_size = 0

    def read(self, *a, **kw):
        text = self.fileobj.read(*a, **kw)
        self.buf.write(text)
        self.current_size += len(text)
        self._check_size()
        return text

    def readline(self, *a, **kw):
        text = self.fileobj.readline(*a, **kw)
        self.buf.write(text)
        self.current_size += len(text)
        self._check_size()
        return text

    def readlines(self):
        return list(self)

    def __iter__(self):
        while True:
            line = self.readline()
            if not line:
                break
            yield line
    
    def close(self):
        self.fileobj.close()

    def change_spy(self, fileobj):
        "Changes the file which recives the spied upon data to fileobj"
        self.buf.flush()
        self.buf.close()
        self.buf = fileobj
        

class SpyHTTPResponse(httplib.HTTPResponse):
    def __init__(self, *a, **kw):
        httplib.HTTPResponse.__init__(self, *a, **kw)
        from . import config
        self.fp = spy(self.fp, None, config.max_payload_size)


class MemFile:
    """Something like StringIO, but switches to a temp file when the maxsize is crossed.
    """
    def __init__(self, maxsize=1024*1024, tmpdir=None, prefix="memfile-", suffix=".tmp"):
        self.maxsize = maxsize
        
        self.tmpdir = tmpdir
        self.prefix = prefix
        self.suffix = suffix

        self._fileobj = StringIO()
        
    def in_memory(self):
        """Returns True if the file is in memory."""
        return not isinstance(self._fileobj, file)
        
    def __getattr__(self, name):
        return getattr(self._fileobj, name)
        
    def _open_tmpfile(self):
        # The TemporaryFile gets deleted automatically when it is closed or when it is garbage collected.
        return tempfile.TemporaryFile(dir=self.tmpdir, prefix=self.prefix, suffix=self.suffix)
        
    def _switch_to_disk(self):
        content = self._fileobj.getvalue()
        self._fileobj = self._open_tmpfile()
        self._fileobj.write(content)
        
    def write(self, data):
        if self.in_memory() and self.tell() + len(data) > self.maxsize:
            self._switch_to_disk()
        self._fileobj.write(data)
        
    def writelines(self, lines):
        for line in lines:
            self.write(line)
            
    def close(self):
        """Deletes the temp file if created.
        """
        if self._fileobj and not self.in_memory():
            logging.info("removing temp file %s", self._fileobj.name)
            os.unlink(self._fileobj.name)

class DummyFilePool:
    """Simple implementation of FilePool.
    """
    counter = 0
    
    def get_file(self):
        filename = "/tmp/record-%d.arc.gz" % self.counter
        while os.path.exists(filename):
            self.counter += 1
            filename = "/tmp/record-%d.arc.gz" % self.counter
        return open(filename, "w")

def fileiter(file, size, chunk_size=1024*10):
    """Returns an iterator over the file for specified size.
    
    The chunk_size specified the amount of data read in each step.
    """
    completed = 0
    while completed < size:
        nbytes = min(size-completed, chunk_size)
        content = file.read(nbytes)
        if not content:
            break
        yield content
        completed += len(content)
        
def test():
    import httplib
    conn = httplib.HTTPConnection("openlibrary.org")
    conn.response_class = SpyHTTPResponse

    conn.request("GET", "/")
    res = conn.getresponse()
    fp = res.fp

    print fp.buf.getvalue()

    res.read()
    print fp.buf.getvalue()

if __name__ == "__main__":
    test()
