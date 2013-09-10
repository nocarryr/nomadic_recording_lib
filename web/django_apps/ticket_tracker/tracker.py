from django.db import models
from models_default_builder import build_defaults
    
class Tracker(models.Model):
    name = models.CharField(max_length=100)
    message_handler = models.ForeignKey('ticket_tracker.EmailHandler', blank=True, null=True)
    
class TrackerPermissionItem(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    inherited = models.ManyToManyField('self', blank=True, null=True)
    models_default_builder_init_data = tracker_item_defaults
    class Meta:
        unique = ('name', )
    @classmethod
    def default_builder_create(cls, **kwargs):
        ckwargs = kwargs.copy()
        inherited = ckwargs.get('inherited')
        if inherited is not None:
            del ckwargs['inherited']
        obj = cls(**ckwargs)
        obj.save()
        if inherited is not None:
            for other in inherited:
                obj.inherited.add(cls.get(name=other))
            obj.save()
    def default_builder_update(self, **kwargs):
        for fname, fval in kwargs.iteritems():
            if fname == 'inherited':
                for othername in fval:
                    self.inherited.add(TrackerPermissionItem.get(name=othername))
            else:
                setattr(self, fname, fval)
    def __unicode__(self):
        desc = self.description
        if desc:
            return desc
        return self.name
    
tracker_item_defaults = ({'name':'read', 'description':'Can Read Posts'}, 
                         {'name':'write', 'description':'Can Reply', 'inherited':['read']}, 
                         {'name':'modify', 'description':'Can Modify Posts', 'inherited':['write']}, 
                         {'name':'take', 'description':'Can Take Ticket as Assignment', 'inherited':['write']}, 
                         {'name':'assign', 'description':'Can Assign Tickets to Staff', 'inherited':['take']}, 
                         {'name':'status_change', 'description':'Can Change Ticket Status', 'inherited':['write']})

build_defaults({'model':TrackerPermissionItem, 'unique':'name', 'defaults':tracker_item_defaults})
    

    
class TrackerGlobalPermission(models.Model):
    permission = models.ForeignKey(TrackerPermissionItem)
    users = models.ManyToManyField('ticket_tracker.StaffUser', null=True, blank=True)
    groups = models.ManyToManyField('ticket_tracker.StaffGroup', null=True, blank=True)
    def __unicode__(self):
        return unicode(self.permission)
        
class TrackerPermission(models.Model):
    permission = models.ForeignKey(TrackerPermissionItem)
    users = models.ManyToManyField('ticket_tracker.StaffUser', null=True, blank=True)
    groups = models.ManyToManyField('ticket_tracker.StaffGroup', null=True, blank=True)
    tracker = models.ForeignKey(Tracker)
    def __unicode__(self):
        return unicode(self.permission)
