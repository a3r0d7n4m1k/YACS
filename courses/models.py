from itertools import product

from django.db import models
from django.conf import settings

from taggit.managers import TaggableManager
from taggit.models import GenericTaggedItemBase, TagBase
from colorful.fields import RGBColorField

from courses import managers
from courses.utils import options, capitalized, sorted_daysofweek


DEBUG = getattr(settings, 'DEBUG', False)
WARN_EXTRA_QUERIES = getattr(settings, 'COURSES_WARN_EXTRA_QUERIES', DEBUG)


__all__ = [
    'Department', 'Semester', 'Period', 'Section', 'SectionCrosslisting',
    'Course', 'OfferedFor', 'SectionPeriod'
]


def has_model(select_related, model):
    return any(s == model._meta.db_table for s, _ in select_related)


def has_prefetched(model_instance, field):
    return field in getattr(model_instance, '_prefetched_objects_cache', [])


def notify_if_missing_prefetch(model_instance, field):
    if WARN_EXTRA_QUERIES and not has_prefetched(model_instance, field):
        print "WARN: DB query for %r. You should probably use prefetch_related." % field


class Tag(TagBase):
    color = RGBColorField(blank=True)

    class Meta:
        verbose_name = 'Tag'
        verbose_name_plural = 'Tags'


class Tagged(GenericTaggedItemBase):
    tag = models.ForeignKey(Tag, related_name="%(app_label)s_%(class)s_items")


def tagged_manager():
    return TaggableManager(through=Tagged)


class Semester(models.Model):
    """Represents the semester / quarter for a college. Courses may not be offered every semester.
    """
    year = models.IntegerField(help_text="The year the semester takes place")
    month = models.IntegerField(help_text="The starting month of the semester")
    name = models.CharField(max_length=100, help_text="An human-readable display of the semester")
    ref = models.CharField(max_length=150, help_text="Internally used by bridge module to refer to a semester.", unique=True)
    date_updated = models.DateTimeField(auto_now=True)
    date_created = models.DateTimeField(auto_now_add=True)
    visible = models.BooleanField(default=True, help_text="Should this semester be publicly visible?")

    objects = managers.QuerySetManager(managers.SerializableQuerySet)
    visible_objects = managers.PublicSemestersQuerySetManager(managers.SerializableQuerySet)

    class Meta:
        unique_together = (
            ('year', 'month'),
        )
        ordering = ['-year', '-month']

    def __unicode__(self):
        return self.name

    def __repr__(self):
        return "<Semester: %d-%d @ %r>" % (self.year, self.month, self.ref)

    def toJSON(self, select_related=()):
        json = {
            'id': self.id,
            'year': self.year,
            'month': self.month,
            'name': self.name,
            'date_updated': self.date_updated,
        }
        if has_model(select_related, Department):
            json['departments'] = self.departments.all().toJSON(select_related)
        return json

    def __cmp__(self, other):
        return cmp(self.year, other.year) or cmp(self.month, other.month)


class Department(models.Model):
    """Represents a department. Provides UI organization capabilities to drill-down courses by department."""
    name = models.CharField(max_length=200, blank=True, default='')
    code = models.CharField(max_length=50, unique=True)
    semesters = models.ManyToManyField(Semester, through='SemesterDepartment', related_name='departments')

    objects = managers.QuerySetManager(managers.SemesterBasedQuerySet)

    class Meta:
        ordering = ['code']

    def __unicode__(self):
        if self.name:
            return u"%s (%s)" % (self.name, self.code)
        return self.code

    def toJSON(self, select_related=()):
        json = {
            'name': self.name,
            'code': self.code,
        }
        if has_model(select_related, Semester):
            json['semesters'] = self.semesters.all().toJSON(select_related)
        return json


class Period(models.Model):
    """Represents a time period that sections are held for during the week.

    For particular details about a section, refer to the SectionPeriod model.
    """
    start = models.TimeField(default=None, null=True)
    end = models.TimeField(default=None, null=True)

    MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = options(7)
    DAYS_OF_WEEK = (
        (MONDAY, 'Monday'),
        (TUESDAY, 'Tuesday'),
        (WEDNESDAY, 'Wednesday'),
        (THURSDAY, 'Thursday'),
        (FRIDAY, 'Friday'),
        (SATURDAY, 'Saturday'),
        (SUNDAY, 'Sunday'),
    )

    days_of_week_flag = models.IntegerField()

    class Meta:
        unique_together = ('start', 'end', 'days_of_week_flag')

    def __unicode__(self):
        return u"%s to %s on %s" % (self.start, self.end, ', '.join(self.days_of_week))

    def toJSON(self, select_related=()):
        return {
            'start_time': self.start,
            'end_time': self.end,
            'days_of_the_week': self.days_of_week,
        }

    @property
    def is_to_be_announced(self):
        return None in (self.start, self.end)

    def conflicts_with(self, period):
        "Returns True if the given period conflicts the current one."
        if self == period:
            return True
        days = self.days_of_week_flag & period.days_of_week_flag
        return days and (
            (self.start <= period.start <= self.end) or
            (self.start <= period.end <= self.end) or
            (period.start <= self.start <= period.end) or
            (period.start <= self.end <= period.end)
        )

    def is_on_day(self, day):
        return self.days_of_week_flag & day

    @property
    def days_of_the_week(self):
        return ', '.join(self.days_of_week)

    @property
    def days_of_week(self):
        "Returns a tuple of days of the week (str)."
        days = []
        for value, name in self.DAYS_OF_WEEK:
            if self.is_on_day(value):
                days.append(name)
        return days

    @days_of_week.setter
    def days_of_week(self, days):
        "Sets the days of the week using a tuple of strings or MONDAY-SUNDAY constants."
        dow = dict((n, v) for v, n in self.DAYS_OF_WEEK)
        value = 0
        for name in set(days):
            if type(name) in (str, unicode):
                value += dow.get(capitalized(name), 0)
            else:
                value += int(name) or 0
        self.days_of_week_flag = value

    def to_tuple(self):
        return (self.start, self.end, self.days_of_week_flag)


class SectionCrosslisting(models.Model):
    """Interface for courses that are crosslisted. Crosslisted sections are similar to each other.

    For example: Grad & Undergrad courses might be crosslisted if they share the same class times & location.
    """
    semester = models.ForeignKey(Semester, related_name='section_crosslistings')
    ref = models.CharField(max_length=200, unique=True, help_text='Internal unique identification used by bridge module.')

    class Meta:
        verbose_name = 'Section Crosslisting'
        verbose_name_plural = 'Section Crosslistings'

    def __unicode__(self):
        return "%s for %s" % (self.semester, self.ref)


class Section(models.Model):
    """Represents a particular course a student can sign up for."""
    STUDY_ABROAD = -1
    OFF_CAMPUS = -2
    number = models.CharField(max_length=5)

    crn = models.IntegerField(db_index=True)
    course = models.ForeignKey('Course', related_name='sections')
    semester = models.ForeignKey(Semester, related_name='sections')
    periods = models.ManyToManyField(Period, through='SectionPeriod', related_name='sections')
    crosslisted = models.ForeignKey(SectionCrosslisting, related_name='sections', null=True, blank=True)

    seats_taken = models.IntegerField('Seats Taken')
    seats_total = models.IntegerField('Seats Total')
    notes = models.TextField(blank=True)

    objects = managers.QuerySetManager(managers.SectionQuerySet)

    class Meta:
        ordering = ['number']

    def __unicode__(self):
        return "%s (%s) Seats: %d / %d" % (self.number, self.crn, self.seats_taken, self.seats_total)

    def __hash__(self):
        return hash(self.id)

    def toJSON(self, select_related=()):
        values = {
            'number': self.number,
            'crn': self.crn,
            'seats_taken': self.seats_taken,
            'seats_total': self.seats_total,
            'seats_left': self.seats_left,
            'notes': list(set(n for n in self.notes.split('\n') if n)),
        }
        if has_model(select_related, Course):
            values['course'] = self.course.toJSON(select_related)
        values['periods'] = [sp.toJSON() for sp in self.get_section_times()]
        return values

    @property
    def is_study_abroad(self):
        return self.number == self.STUDY_ABROAD

    @property
    def is_full(self):
        return self.seats_left <= 0

    @property
    def seats_left(self):
        return max(self.seats_total - self.seats_taken, 0)

    @property
    def days_of_week(self):
        dows = set()
        for period in self.get_periods():
            dows.update(period.days_of_week)
        return sorted_daysofweek(dows)

    @property
    def instructors(self):
        return set([ps.instructor for ps in self.get_section_times()])

    def get_section_times(self):
        if WARN_EXTRA_QUERIES and not has_prefetched(self, 'section_times'):
            print "WARN: DB query call for 'section_times'. You should probably use prefetch_related."
        return self.section_times.all()

    def get_periods(self):
        if WARN_EXTRA_QUERIES and not has_prefetched(self, 'periods'):
            print "WARN: DB query for 'periods'. You should probably use prefetch_related."
        return self.periods.all()

    def conflicts_with(self, section):
        "Returns True if the given section conflicts with another provided section."
        # always conflicts with itself...
        if self == section:
            return True
        # START --- this should really be a proxy in scheduler.models.SectionProxy
        # but there seems to be a django bug with Proxy models causing tests to fail.
        # self.conflicts has to be set by the view....
        if hasattr(self, 'conflicts'):
            return section.id in self.conflicts
        # END ---
        for period1, period2 in product(self.get_periods(), section.get_periods()):
            if period1 == period2 or period1.conflicts_with(period2):
                return True
        return False


class Course(models.Model):
    """A course offered."""
    name = models.CharField(max_length=200)
    number = models.IntegerField()

    department = models.ForeignKey(Department, related_name='courses')
    semesters = models.ManyToManyField(Semester, through='OfferedFor', related_name='courses')

    description = models.TextField(default="")
    min_credits = models.IntegerField('Min Credits')
    max_credits = models.IntegerField('Max Credits')

    grade_type = models.CharField(max_length=150, blank=True, default='')
    prereqs = models.TextField(default="")
    is_comm_intense = models.BooleanField('Communication Intensive', default=False)

    objects = managers.QuerySetManager(managers.CourseQuerySet)
    tags = tagged_manager()

    class Meta:
        ordering = ['department__code', 'number']

    def __unicode__(self):
        return '%s (%s %d)' % (
            self.name, self.department.code, self.number
        )

    def __hash__(self):
        return hash(self.id)

    def conflicts_with(self, course):
        "Returns True if the provided course conflicts with this one on time periods."
        sections = course.sections.all()
        for section1 in self.sections.all():
            for section2 in sections:
                if section1.conflicts_with(section2):
                    return True
        return False

    def toJSON(self, select_related=()):
        values = {
            'id': self.pk,
            'name': self.name,
            'number': self.number,
            'min_credits': self.min_credits,
            'max_credits': self.max_credits,
            'description': self.description,
            'prereqs': self.prereqs,
            'is_comm_intense': self.is_comm_intense,
        }
        if has_model(select_related, Department):
            values['department'] = self.department.toJSON(select_related)
        if has_prefetched(self, 'semesters'):
            values['semesters'] = [s.id for s in self.semesters.all()]
        if has_prefetched(self, 'sections'):
            values['sections'] = [s.toJSON() for s in self.sections.all()]
        return values

    @property
    def code(self):
        "Returns the department code and course number as a string."
        return '%s %s' % (self.department.code, self.number)

    @property
    def credits_display(self):
        "Returns the number of credits the course for those needy humans."
        if self.min_credits == self.max_credits:
            return "%d credit%s" % (self.min_credits, '' if self.min_credits == 1 else 's')
        return "%d - %d credits" % (self.min_credits, self.max_credits)

    @property
    def num_sections_display(self):
        section_count = self.sections.count()
        return "%d section%s" % (section_count, '' if section_count == 1 else 's')

    @property
    def seats_left_display(self):
        seats_left = self.seats_left
        return "%d seat%s" % (seats_left, '' if seats_left == 1 else 's')

    @property
    def tags(self):
        tags = []
        section_types = {
            'LEC': {
                'name': 'Lecture',
                'title': 'This course has lecture, where the instructor teaches the course.',
                'sort_order': 0
            },
            'TES': {
                'name': 'Testing',
                'title': 'This course has a testing period outside normal lecture or recitation.',
                'sort_order': 5
            },
            'REC': {
                'name': 'Recitation',
                'title': 'This course has recitation, where problemsets and quizzes generally occur.',
                'sort_order': 2
            },
            'LAB': {
                'name': 'Lab',
                'title': 'This course has lab, where hands-on activities occur.',
                'sort_order': 1
            },
            'STU': {
                'name': 'Studio',
                'title': 'This course has studio',
                'sort_order': 4
            }
        }
        assigned_tags = set([])
        for section_period in self.section_periods:
            tag = section_types.get(section_period.kind)
            if tag and tag['name'] not in assigned_tags:
                tags.append(tag)
                assigned_tags = assigned_tags.union([tag['name']])
        if self.is_comm_intense:
            tags.append({
                'name': 'Comm Intensive',
                'title': 'This course counts as a communication intensive course.',
                'classes': 'satisfies-requirement',
                'sort_order': 10
            })
        if self.grade_type == 'Satisfactory/Unsatisfactory':
            tags.append({
                'name': 'Pass/Fail',
                'title': "This course's final grade is pass or fail instead of a GPA.",
                'classes': 'pass_or_fail',
                'sort_order': 11
            })
        return tags

    @property
    def available_sections(self):
        return self.sections.by_availability()

    # TODO: These few properties should be moved into a manager for query optimization
    @property
    def section_periods(self):
        if not hasattr(self, 'all_section_periods'):
            return SectionPeriod.objects.by_course(course=self)
        return self.all_section_periods

    @property
    def notes(self):
        def _process(notes):
            lines = set([line for note in notes for line in note.split('\n')])
            return lines
        return _process(set(sp.section.notes for sp in self.section_times))

    @property
    def section_ids(self):
        notify_if_missing_prefetch(self, 'sections')
        return set(section.id for section in self.sections.all())

    @property
    def full_section_ids(self):
        notify_if_missing_prefetch(self, 'sections')
        return set(s.id for s in self.sections.all() if s.seats_taken >= s.seats_total)

    @property
    def crns(self):
        notify_if_missing_prefetch(self, 'sections')
        return set(section.crn for section in self.sections.all())

    @property
    def full_crns(self):
        notify_if_missing_prefetch(self, 'sections')
        return set(s.crn for s in self.sections.all() if s.seats_taken >= s.seats_total)

    @property
    def seats_left(self):
        notify_if_missing_prefetch(self, 'sections')
        return sum(s.seats_total - s.seats_taken for s in self.sections.all())

    @property
    def section_times(self):
        notify_if_missing_prefetch(self, 'sections')
        section_periods = []
        for section in self.sections.all():
            notify_if_missing_prefetch(section, 'section_times')
            section_periods.extend(section.section_times.all())
        return set(section_periods)

    @property
    def instructors(self):
        return set(sp.instructor for sp in self.section_times)

    @property
    def kinds(self):
        return set(st.kind for st in self.section_times)


class OfferedFor(models.Model):
    "The M2M model of courses and semesters."
    course = models.ForeignKey('Course', related_name='offered_for')
    ref = models.CharField(max_length=200, blank=True, help_text='Internal. Used by data source to identify unique offerings.', db_index=True)
    semester = models.ForeignKey('Semester', related_name='offers')

    class Meta:
        unique_together = ('course', 'semester')
        verbose_name = 'Offers'
        verbose_name_plural = 'Offerings'

    def __unicode__(self):
        return u"%s is offered for %s" % (self.course, self.semester)


class SectionPeriod(models.Model):
    "M2M model of sections and periods"
    period = models.ForeignKey('Period', related_name='section_times')
    section = models.ForeignKey('Section', related_name='section_times')

    # we could do M2M here, but the other data here is related, and it's just easier have one link
    # per semeter...
    semester = models.ForeignKey('Semester', related_name='section_times')
    instructor = models.CharField(max_length=150, blank=True)
    location = models.CharField(max_length=150, blank=True)
    kind = models.CharField(max_length=75, help_text="The kind of meeting time (eg - lab, recitation, lecture, etc.)")

    objects = managers.QuerySetManager(managers.SectionPeriodQuerySet)

    class Meta:
        unique_together = (
            ('period', 'section', 'semester'),
        )
        verbose_name = 'Section Period'
        verbose_name_plural = 'Section Periods'

    def __unicode__(self):
        return "%s holds %s during %r at %s for section %s" % (self.instructor, self.kind, self.period, self.location, self.section)

    def toJSON(self, select_related=()):
        json = {
            'id': self.id,
            'instructor': self.instructor,
            'location': self.location,
            'kind': self.kind,
        }
        json.update(self.period.toJSON())
        return json

    def conflicts_with(self, section_period):
        "Returns True if times conflict with the given section period."
        return self.period.conflicts_with(section_period.period)


class SemesterDepartment(models.Model):
    "M2M model of departments and semesters."
    department = models.ForeignKey('Department', related_name='+')
    semester = models.ForeignKey('Semester', related_name='+')

    class Meta:
        unique_together = ('department', 'semester')
