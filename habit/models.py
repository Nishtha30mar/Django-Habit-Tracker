from datetime import timedelta
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from .utils import convert_period_to_days


class Habit(models.Model):
    """
    Represents a habit tracked by the user.
    """

    name = models.CharField(max_length=255)
    frequency = models.IntegerField(default=1)
    period = models.CharField(max_length=255)
    goal = models.IntegerField(default=90)
    num_of_tasks = models.IntegerField()
    notes = models.CharField(max_length=255, default=None, blank=True, null=True)
    creation_time = models.DateTimeField(auto_now_add=True)
    start_date = models.DateTimeField(null=True, blank=True)
    completion_date = models.DateTimeField(null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.lower()

        if not self.completion_date and self.start_date:
            self.completion_date = self.start_date + timedelta(days=self.goal)

        if self.period and self.goal:
            num_of_period = convert_period_to_days(self.period)
            if not self.num_of_tasks and num_of_period > 0:
                self.num_of_tasks = (self.goal // num_of_period) * self.frequency

        super().save(*args, **kwargs)


class TaskTracker(models.Model):
    """
    Represents a tracker for habit-related tasks.
    """

    habit = models.ForeignKey(Habit, on_delete=models.CASCADE)
    start_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    task_number = models.IntegerField()
    task_status = models.CharField(max_length=255, default='In progress')
    task_completion_date = models.DateTimeField(null=True, blank=True)

    @classmethod
    def create_tasks(cls, habit, n=0):
        if not habit.start_date or habit.num_of_tasks <= 0:
            return

        period_days = convert_period_to_days(habit.period)
        total_periods = habit.goal // period_days
        task_number = n + 1

        for period_index in range(total_periods):
            period_start = habit.start_date + timedelta(days=period_index * period_days)
            period_due = period_start

            for _ in range(habit.frequency):
                cls.objects.create(
                    habit=habit,
                    start_date=period_start,
                    due_date=period_due,
                    task_number=task_number,
                    task_status='In progress'
                )
                task_number += 1
                
    @classmethod
    def update_failed_tasks(cls, user_id):
        updated_habit_ids = []
        updated_task_ids = []
        now = timezone.now()
        
        tasks_to_update = cls.objects.filter(
            habit__user_id=user_id,
            due_date__lt=now,
            task_status='In progress'
        )
        
        for task in tasks_to_update:
            task.task_status = 'Failed'
            task.task_completion_date = task.due_date
            task.save()
            updated_habit_ids.append(task.habit_id)
            updated_task_ids.append(task.id)
            
        return (updated_habit_ids, updated_task_ids)


class Streak(models.Model):
    """
    Represents a streak associated with a habit.
    """
    habit = models.ForeignKey(Habit, on_delete=models.CASCADE, related_name='streak')
    num_of_completed_tasks = models.IntegerField(default=0)
    num_of_failed_tasks = models.IntegerField(default=0)
    longest_streak = models.IntegerField(default=0)
    current_streak = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak
        super().save(*args, **kwargs)

    @classmethod
    def calculate_streak_from_tasks(cls, habit_id):
        """
        Calculate streak using only finished tasks.
        Future/In progress tasks should not break the current streak.
        """

        finished_tasks = TaskTracker.objects.filter(
            habit_id=habit_id,
            task_status__in=['Completed', 'Failed']
        ).order_by('task_number')

        current_streak = 0
        for task in finished_tasks.order_by('-task_number'):
            if task.task_status == 'Completed':
                current_streak += 1
            else:
                break

        longest_streak = 0
        temp_streak = 0

        for task in finished_tasks:
            if task.task_status == 'Completed':
                temp_streak += 1
                longest_streak = max(longest_streak, temp_streak)
            else:
                temp_streak = 0

        completed_count = TaskTracker.objects.filter(
            habit_id=habit_id,
            task_status='Completed'
        ).count()

        failed_count = TaskTracker.objects.filter(
            habit_id=habit_id,
            task_status='Failed'
        ).count()

        return current_streak, longest_streak, completed_count, failed_count

    @classmethod
    def sync_streak_with_tasks(cls, habit_id):
        """
        Completely synchronizes streak data with actual task statuses.
        """
        current_streak, longest_streak, completed_count, failed_count = cls.calculate_streak_from_tasks(habit_id)
        
        streak, created = cls.objects.get_or_create(habit_id=habit_id)
        streak.current_streak = current_streak
        streak.longest_streak = longest_streak
        streak.num_of_completed_tasks = completed_count
        streak.num_of_failed_tasks = failed_count
        streak.save()
        
        return streak

    @classmethod
    def update_streak_on_completion(cls, habit_id):
        """
        Updates streak when a task is completed.
        """
        return cls.sync_streak_with_tasks(habit_id)

    @classmethod
    def update_streak_on_failure(cls, habit_ids):
        """
        Updates streak when tasks fail.
        """
        for habit_id in habit_ids:
            cls.sync_streak_with_tasks(habit_id)


class Achievement(models.Model):
    """
    Represents an achievement associated with a habit.
    """
    habit = models.ForeignKey(Habit, on_delete=models.CASCADE, related_name='achievement')
    streak_length = models.IntegerField(default=0)
    title = models.CharField(max_length=255)
    date = models.DateTimeField(null=True, blank=True)

    @classmethod
    def update_achievements(cls, tasks):
        for task in tasks:
            try:
                if task.task_number > 1:
                    try:
                        prev_task = TaskTracker.objects.get(
                            habit=task.habit, 
                            task_number=task.task_number - 1
                        )
                        if prev_task.task_status == 'Failed':
                            continue
                    except TaskTracker.DoesNotExist:
                        pass
                
                streak = Streak.objects.filter(habit=task.habit).first()
                if streak and streak.current_streak > 0:
                    title = 'Break The Habit'
                    cls.objects.create(
                        habit=task.habit, 
                        date=task.due_date,
                        title=title, 
                        streak_length=streak.current_streak
                    )
            except Exception:
                pass

    @classmethod
    def rewards_streaks(cls, habit_id, streak):
        try:
            habit = Habit.objects.get(pk=habit_id)
        except Habit.DoesNotExist:
            return

        if habit.period == 'daily':
            if streak.current_streak >= 7 and streak.current_streak < 14:
                if not cls.objects.filter(habit=habit, title='7-Day Streak').exists():
                    cls.objects.create(habit=habit, date=timezone.now(), title='7-Day Streak', streak_length=7)
            elif streak.current_streak >= 14 and streak.current_streak < 30:
                if not cls.objects.filter(habit=habit, title='14-Day Streak').exists():
                    cls.objects.create(habit=habit, date=timezone.now(), title='14-Day Streak', streak_length=14)
            elif streak.current_streak >= 30:
                if not cls.objects.filter(habit=habit, title='30-Day Streak').exists():
                    cls.objects.create(habit=habit, date=timezone.now(), title='30-Day Streak', streak_length=30)

        elif habit.period == 'weekly':
            if streak.current_streak >= 1 and streak.current_streak < 2:
                if not cls.objects.filter(habit=habit, title='1-Week Streak').exists():
                    cls.objects.create(habit=habit, date=timezone.now(), title='1-Week Streak', streak_length=1)
            elif streak.current_streak >= 2 and streak.current_streak < 4:
                if not cls.objects.filter(habit=habit, title="2-Week's Streak").exists():
                    cls.objects.create(habit=habit, date=timezone.now(), title="2-Week's Streak", streak_length=2)
            elif streak.current_streak >= 4:
                if not cls.objects.filter(habit=habit, title="4-Week's Streak").exists():
                    cls.objects.create(habit=habit, date=timezone.now(), title="4-Week's Streak", streak_length=4)

        elif habit.period == 'monthly':
            if streak.current_streak >= 1 and streak.current_streak < 2:
                if not cls.objects.filter(habit=habit, title='1-Month Streak').exists():
                    cls.objects.create(habit=habit, date=timezone.now(), title='1-Month Streak', streak_length=1)
            elif streak.current_streak >= 2 and streak.current_streak < 4:
                if not cls.objects.filter(habit=habit, title="2-Month's Streak").exists():
                    cls.objects.create(habit=habit, date=timezone.now(), title="2-Month's Streak", streak_length=2)
            elif streak.current_streak >= 4:
                if not cls.objects.filter(habit=habit, title="4-Month's Streak").exists():
                    cls.objects.create(habit=habit, date=timezone.now(), title="4-Month's Streak", streak_length=4)