import threading
import traceback
import collections
import functools
import types
#import gtk
#import gobject
from ui_modules import gtk, gobject, gdk, glib

from Bases import BaseObject, BaseThread
from ...bases import simple

GTK_VERSION = BaseObject().GLOBAL_CONFIG['gtk_version']

def get_gtk2_enum(name):
    keys = [s for s in dir(gtk) if s[:len(name)+1] == name+'_']
    return dict(zip([key.split(name+'_')[1] for key in keys], [getattr(gtk, key) for key in keys]))
def get_gtk3_enum(name):
    obj = getattr(gtk, name)
    keys = [s for s in dir(obj) if s.isupper()]
    return dict(zip(keys, [getattr(obj, key) for key in keys]))

class GTask(BaseThread):
    _Events = {'work_done':{}}
    def __init__(self, **kwargs):
        super(GTask, self).__init__(**kwargs)
        self.work_callback = kwargs.get('work_callback', self._work_callback)
        self.done_callback = kwargs.get('done_callback', self._done_callback)
        self.work_kwargs = kwargs.get('kwargs', {})
        self.work_args = kwargs.get('args', ())
        #self.running = threading.Event()
        #self.work_done = threading.Event()
        
    def run(self):
        self._running.set()
        self.work_callback(*self.work_args, **self.work_kwargs)
        self.work_done.set()
        self.done_callback(self)
        
    def _work_callback(self, *args, **kwargs):
        pass
        
    def _done_callback(self, *args):
        pass
    
class GCallbackInserter(BaseThread):
    _Events = {'active':{}, 
               'have_gtk_lock':{}}
    def __init__(self, **kwargs):
        kwargs['thread_id'] = 'GtkCallbackInserter'
        kwargs['disable_threaded_call_waits'] = True
        super(GCallbackInserter, self).__init__(**kwargs)
        #self.running = threading.Event()
        #self.active = threading.Event()
        #self.have_gtk_lock = threading.Event()
        self.queue = collections.deque()
        self.cb_data = {}
        
    def add_callback(self, cb, *args, **kwargs):
        #cbid = id(cb)
        obj = cb.im_self
        key = (id(obj), cb.im_func.func_name)
        #if obj and obj.__class__.__name__ == 'ColorBtn':
        #    prop = cb.im_self.Property
        #    if prop and prop.parent_obj.parent.Index == 2:
        #        print 'addcb: ', cbid, cbid in self.queue
        if key in self.queue and self.queue[0] != key:
            self.queue.remove(key)
            #print 'removed existing cb: ', key
        self.queue.append(key)
        self.cb_data[key] = (cb, args, kwargs)
        self.active.set()
        
    def _thread_loop_iteration(self):
        self.active.wait()
        if not self._running.isSet():
            return
        if self.have_gtk_lock.isSet():
            r = self._next_callback()
            if r is False:
                self._release_gtk_lock()
                self.active.clear()
                #print 'queue=%s, cbdata=%s' % (self.queue, self.cb_data)
        else:
            gobject.idle_add(self._on_gtk_idle)
            self.have_gtk_lock.wait()
            #print 'lock acquired, len: ', len(self.queue)
    def stop(self, **kwargs):
        self._running.clear()
        self.active.set()
        super(GCallbackInserter, self).stop(**kwargs)
        if self.have_gtk_lock.isSet():
            self._release_gtk_lock()
            
    def old_run(self):
        self.running.set()
        while self.running.isSet():
            self.active.wait()
            if self.running.isSet():
                if self.have_gtk_lock.isSet():
                    r = self._next_callback()
                    if r is False:
                        self._release_gtk_lock()
                        self.active.clear()
                        #print 'queue=%s, cbdata=%s' % (self.queue, self.cb_data)
                else:
                    #gobject.idle_add(self._on_gtk_idle)
                    #gdk.threads_add_idle(self._on_gtk_idle, None)
                    glib.idle_add(self._on_gtk_idle)
                    self.have_gtk_lock.wait()
                    #print 'lock acquired, len: ', len(self.queue)
                
    def old_stop(self):
        self.running.clear()
        self.active.set()
        if self.have_gtk_lock.isSet():
            self._release_gtk_lock()
                
    def _on_gtk_idle(self, *args):
        gdk.threads_enter()
        self.have_gtk_lock.set()
        return False
        
    def _release_gtk_lock(self):
        gdk.threads_leave()
        self.have_gtk_lock.clear()
        #print 'lock released, len: ', len(self.queue)
            
    def _next_callback(self):
        if not len(self.queue):
            #self.active.clear()
            return False
        #print 'cb len=%s, have_lock=%s' % (len(self.queue), self.have_gtk_lock.isSet())
        key = self.queue.popleft()
        if key in self.cb_data:
            cb, args, kwargs = self.cb_data[key]
            del self.cb_data[key]
            try:
                cb(*args, **kwargs)
            except:
                self.LOG.warning('GTK thread insertion error: \n' + traceback.format_exc())
        return True

gCBThread = GCallbackInserter()
gCBThread.start()

def thread_to_gtk(cb, *args, **kwargs):
    if threading.currentThread().name == 'MainThread':
        cb(*args, **kwargs)
        return
    #print 'THREAD_TO_GTK: ', threading.currentThread().name, cb, args, kwargs
    gCBThread.add_callback(cb, *args, **kwargs)
    
class ThreadToGtk(object):
    def __init__(self, f):
        self.f = f
    def __get__(self, instance, cls):
        if instance is not None:
            return self.make_bound(instance, cls)
    def make_bound(self, instance, cls):
        def wrapper(*args, **kwargs):
            if len(args):
                if args[0] == wrapper.callback.im_self:
                    args = args[1:]
            #print 'thread_to_gtk wrapper: ', wrapper.callback, args, kwargs
            thread_to_gtk(wrapper.callback, *args, **kwargs)
        def called(*args, **kwargs):
            #print 'called: ', args, kwargs
            self.f(*args, **kwargs)
        called.__name__ = self.f.__name__ + '_ThreadToGtk_callback'
        cb_method = types.MethodType(called, instance, cls)
        wrapper.callback = cb_method
        wrapper.__name__ = self.f.__name__
        new_method = types.MethodType(wrapper, instance, cls)
        #setattr(instance, self.f.__name__ + '_ThreadToGtk_callback', cb_method)
        #setattr(instance, self.f.__name__, new_method)
        #print 'make_bound: instance=%s, cb_method=%s, new_method=%s, f=%s, wrapper=%s' % (instance, cb_method, new_method, self.f, wrapper)
        return new_method
    
    
def gtk_to_thread(**kwargs):
    auto_start = kwargs.get('auto_start', True)
    task = GTask(**kwargs)
    if auto_start:
        task.start()
    return task
    
class Color(simple.Color):
    def __init__(self, **kwargs):
        self._gtasks = collections.deque()
        super(Color, self).__init__(**kwargs)
    def blahon_widget_update(self, *args, **kwargs):
        if self.widget_set_by_program:
            return
        tkwargs = dict(auto_start=False, 
                       work_callback=super(Color, self).on_widget_update, 
                       done_callback=self._on_gtask_done, 
                       kwargs=kwargs)
        task = gtk_to_thread(**tkwargs)
        self._gtasks.append(task)
        if len(self._gtasks) == 1:
            self._next_gtask()
    def _next_gtask(self):
        if not len(self._gtasks):
            #print 'all threads: ', threading.enumerate()
            return
        task = self._gtasks.popleft()
        task.start()
    def _on_gtask_done(self, task):
        #print task, 'done, len = ', len(self._gtasks)
        self._next_gtask()

class EntryBuffer(simple.EntryBuffer):
    pass
    
class TextBuffer(BaseObject):
    def __init__(self, **kwargs):
        super(TextBuffer, self).__init__(**kwargs)
        self.register_signal('modified')
        self.src_object = kwargs.get('src_object')
        self.src_attr = kwargs.get('src_attr')
        self.allow_obj_setattr = kwargs.get('allow_obj_setattr', False)
        self.id = kwargs.get('id')
        self.buffer = gtk.TextBuffer()
        self.buffer.connect('begin-user-action', self.on_begin_action)
        self.buffer.connect('end-user-action', self.on_end_action)
        self.widget = kwargs.get('widget')
        if self.widget is not None:
            self.widget.set_buffer(self.buffer)
        
        if self.src_object is not None and self.src_attr is not None:
            self.update_text_from_object()
    
    def get_text(self):
        args = [self.buffer.get_start_iter(), self.buffer.get_end_iter()]
        args.append(True)
        self._modified = False
        return self.buffer.get_text(*args)
    
    def set_text(self, text):
        self.buffer.set_text(str(text))
        self._modified = False
    
    @ThreadToGtk
    def update_text_from_object(self, *args, **kwargs):
        obj_text = getattr(self.src_object, self.src_attr)
        if obj_text != self.get_text():
            self.set_text(obj_text)
            end = self.buffer.get_end_iter()
            self.widget.scroll_to_iter(end, 0., False, 0, 0)
    
    def update_object_from_text(self, *args, **kwargs):
        obj_text = getattr(self.src_object, self.src_attr)
        bfr_text = self.get_text()
        if bfr_text != obj_text:
            setattr(self.src_object, self.src_attr, bfr_text)
        
    def on_begin_action(self, *args):
        #print 'action begin'
        self._modified = True
    
    def on_end_action(self, *args):
        text = self.get_text()
        #print 'action end'
        #self._modified = True
        if self.allow_obj_setattr:
            #setattr(self.src_object, self.src_attr, text)
            self.update_object_from_text()
        self.emit('modified', id=self.id, text=text)
        
#    def update_name_from_buffer(self):
#        buffer = self.textBufferName
#        if self.currentParameter is not None:# and buffer.get_modified is True:
#            text = self.get_buffer_text()
#            if text != self.currentParameter.name:
#                self.currentParameter.name = text
#                buffer.set_modified(False)
        

class Spin(simple.Spin):
    pass

class Radio(simple.Radio):
    def __init__(self, **kwargs):
        self._root_widget = None
        super(Radio, self).__init__(**kwargs)
    def build_widget(self, key):
        w = gtk.RadioButton(group=self._root_widget, label=key)
        id = w.connect('clicked', self.on_widgets_clicked)
        self.widget_signals[key] = id
        if self._root_widget is None:
            self._root_widget = w
        return w
    def remove_widgets(self):
        for key, w in self.widgets.iteritems():
            w.disconnect(self.widget_signals[key])
            w.get_parent().remove(w)
        self._root_widget = None
    
class Toggle(simple.Toggle):
    pass
 
class Fader(simple.Fader):
    def setup_widgets(self, **kwargs):
        self.widget_signals = set()
        fader_types = {'VSlider':gtk.VScale, 'HSlider':gtk.HScale}
        fader_type = kwargs.get('fader_type')
        if not hasattr(self, 'widget'):
            self.widget = fader_types[fader_type]()
        #self.widget.set_draw_value(False)
        self.widget_packing = {'expand':True}
        
        adj_kwargs = {'value':0, 'lower':self.value_range[0], 'upper':self.value_range[1]}
        adj_kwargs.update(kwargs.get('adj_kwargs', {}))
        self.adj = gtk.Adjustment(**adj_kwargs)
        self.adj.set_step_increment(1)
        self.widget.set_adjustment(self.adj)
        
        #id = self.widget.connect('change-value', self.on_widget_change_value)
        #self.widget_signals.add(id)
        id = self.adj.connect('value-changed', self.on_widget_change_value)
        self.widget_signals.add(id)
        id = self.widget.connect('button-press-event', self.on_widget_button_press)
        self.widget_signals.add(id)
        id = self.widget.connect('button-release-event', self.on_widget_button_release)
        self.widget_signals.add(id)
        id = self.widget.connect('format-value', self.on_widget_format_value)
        self.widget_signals.add(id)
    
    def unlink(self):
        for id in self.widget_signals:
            self.widget.disconnect(id)
        self.widget_signals.clear()
        super(Fader, self).unlink()
        
    @ThreadToGtk
    def set_widget_value(self, value):
        if value is None:
            value = 0
        #thread_to_gtk(self._do_set_widget_value, value)
        self.adj.set_value(value)
        
    def get_widget_value(self):
        return self.adj.get_value()
        
    def set_widget_range(self):
        if type(self.value_range[1]) == float:
            step = .1
        else:
            step = 1
        keys = ['lower', 'upper', 'step-increment']
        vals = self.value_range[:]
        vals.append(step)
        for key, val in zip(keys, vals):
            self.adj.set_property(key, val)
        
    def on_widget_button_press(self, *args):
        self.widget_is_adjusting = True
        
    def on_widget_button_release(self, *args):
        self.widget_is_adjusting = False
        
    def on_widget_format_value(self, widget, value):
        return self.value_fmt_string % {'value':value, 'symbol':self.value_symbol}
        
class ScaledFader(simple.ScaledFader):
    def setup_widgets(self, **kwargs):
        fader_types = {'VSlider':gtk.VScale, 'HSlider':gtk.HScale}
        fader_type = kwargs.get('fader_type')
        if not hasattr(self, 'widget'):
            self.widget = fader_types[fader_type]()
        self.widget_packing = {'expand':True}
        
        adj_kwargs = {'value':0, 'lower':self.ui_scale['min'], 'upper':self.ui_scale['max']}
        adj_kwargs.update(kwargs.get('adj_kwargs', {}))
        self.adj = gtk.Adjustment(**adj_kwargs)
        self.adj.set_step_increment(1)
        self.widget.set_adjustment(self.adj)
        
        id = self.widget.connect('change-value', self.on_widget_change_value)
        self.widget_signals.append(id)
        id = self.widget.connect('button-press-event', self.on_widget_button_press)
        self.widget_signals.append(id)
        id = self.widget.connect('button-release-event', self.on_widget_button_release)
        self.widget_signals.append(id)
    
    def on_widget_change_value(self, range, scroll, value):
        self.scaler.set_value('ui', value)
        #print 'widget: ', value
        return False
        
    @ThreadToGtk
    def set_widget_value(self, value):
        if value is None:
            value = 0
        #thread_to_gtk(self._do_set_widget_value, value)
        self.adj.set_value(value)
    

class Meter(BaseObject):
    def __init__(self, **kwargs):
        super(Meter, self).__init__(**kwargs)
        

class TreeModelSort(gtk.TreeModelSort):
    def __init__(self, *args, **kwargs):
        model = kwargs.get('model')
        if not model:
            model = args[0]
        if GTK_VERSION < 3:
            super(TreeModelSort, self).__init__(model)
            enums = {True:gtk.SORT_ASCENDING, False:gtk.SORT_DESCENDING}
        else:
            super(TreeModelSort, self).__init__(model=model)
            stype = gtk.SortType
            enums = {True:stype.ASCENDING, False:stype.DESCENDING}
        self.sort_direction_enums = enums
    def set_sort_column_id(self, column_index, direction):
        if isinstance(direction, bool):
            direction = self.sort_direction_enums[direction]
        super(TreeModelSort, self).set_sort_column_id(column_index, direction)
    def convert_child_iter_to_iter(self, c_iter):
        if GTK_VERSION < 3:
            return super(TreeModelSort, self).convert_child_iter_to_iter(None, c_iter)
        else:
            result, iter = super(TreeModelSort, self).convert_child_iter_to_iter(c_iter)
            if result:
                return iter
        
