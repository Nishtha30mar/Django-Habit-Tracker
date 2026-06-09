import json
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.utils import timezone
from django.core import serializers
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum, Avg, Max, Min, F
from .forms import HabitForm
from .models import TaskTracker, Habit, Streak, Achievement

from .analytics import (
    due_today_tasks, active_tasks, upcoming_tasks, fully_completed_habits,
    calculate_progress, longest_current_streak_over_all_habits,
    all_tracked_habits, habits_by_period,
    longest_streak_over_all_habits, num_inprogress_tasks,
    update_user_activity, rank_habits, all_completed_habits
)


class HabitView(View):
    """
    View class for handling habit-related operations.

    Methods
    -------
    get(request, *args, **kwargs)
        Handles GET requests for displaying the home page.
    post(request, *args, **kwargs)
        Handles POST requests for completing tasks.
    about(request)
        Displays the About page.
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """
        Handles GET requests for displaying the home page.

        Parameters
        ----------
        request : HttpRequest
            The HTTP request.

        Returns
        -------
        HttpResponse
            The HTTP response.
        """
        user_id = request.user.id
        update_user_activity(user_id)
        today_tasks = due_today_tasks(user_id=user_id)
        active_task = active_tasks(user_id=user_id)
        upcoming_task = upcoming_tasks(user_id=user_id)
        completed_habits = fully_completed_habits(user_id)
        
        user = User.objects.get(id=user_id)
        full_name = user.get_full_name().strip()

        if full_name:
            user_full_name = full_name.split()[0].capitalize()
        else:
            user_full_name = user.username.capitalize()
            
        current_streak = Streak.objects.filter(
            habit__user=request.user
        ).aggregate(Max('current_streak'))['current_streak__max'] or 0
        
        context = {
            'upcoming_tasks': upcoming_task,
            'due_today_tasks': today_tasks,
            'available_tasks': active_task,
            'completed_habits': completed_habits,
            'user_full_name': user_full_name,
            'current_streak': current_streak,
        }

        return render(request, 'home.html', context)

    def post(self, request, *args, **kwargs):
        """
        Handles POST requests for completing tasks.
        """
        task_id = request.POST.get('task_id')
        habit_id = request.POST.get('habit_id')

        task = get_object_or_404(TaskTracker, id=task_id)
        habit = get_object_or_404(Habit, id=habit_id)

        try:
            # Update Task table
            task.task_status = 'Completed'
            task.task_completion_date = timezone.now()
            task.save()

            # Update streak using the corrected method
            streak = Streak.update_streak_on_completion(habit_id)
            
            # Check for achievements
            Achievement.rewards_streaks(habit_id, streak)

            return redirect('habit-home')

        except TaskTracker.DoesNotExist:
            pass

        return redirect('habit-home')


class HabitManagerView(View):
    """
    View class for managing habits.

    Methods
    -------
    active_habits(request)
        Displays active habits for the logged-in user.
    habit_detail(request, habit_id)
        Displays detailed information about a habit.
    add_habit(request)
        Handles adding a new habit.
    delete_habit(request, habit_id)
        Handles deleting a habit.
    """
    
    @staticmethod
    def add_habit(request):
        """
        Handles adding a new habit.

        Parameters
        ----------
        request : HttpRequest
            The HTTP request.

        Returns
        -------
        HttpResponse
            The HTTP response.
        """
        if not request.user.is_authenticated:
            return redirect('login')
        pre_defined_habits = {
                            'Exercise': {
                                'frequency': '2',
                                'period': 'weekly',
                                'goal': '30',
                                'notes': 'Exercising regularly to maintain physical fitness.'
                            },
                            'Reading': {
                                'frequency': '1',
                                'period': 'daily',
                                'goal': '30',
                                'notes': 'Reading habit for personal growth and learning.'
                            },
                            'Brush your Teeth': {
                                'frequency': '2',
                                'period': 'daily',
                                'goal': '30',
                                'notes': 'Reminder to maintain oral hygiene by brushing teeth twice daily.'
                            },
                            'Budgeting': {
                                'frequency': '1',
                                'period': 'weekly',
                                'goal': '30',
                                'notes': 'Budget finances regularly for financial stability and planning'
                            },
                            'Meditation': {
                                'frequency': '1',
                                'period': 'daily',
                                'goal': '30',
                                'notes': 'Daily meditation practice for mental well-being and stress relief.'
                            },
                             'Monthly Review': {
                                'frequency': '1',
                                'period': 'monthly',
                                'goal': '365',
                                'notes': 'Reflect on achievements and set goals for the upcoming month.'
                            }
                        }
        if request.method == 'POST':
            form = HabitForm(request.POST)
            if form.is_valid():
                # Validate if the goal is smaller than the period
                if not form.is_goal_achievable():
                    messages.error(request, '''The frequency results in a goal that is not
                                achievable. Choose a longer goal.''')
                    return render(request, 'add_habit.html', {'form': form})

                # Validate if the habit name is not already used or existed
                if not form.is_valid_habit_name(request.user):
                    messages.error(request, "You already used that name for another habit")
                    return render(request, 'add_habit.html', {'form': form})

                start_date = form.cleaned_data['start_date']
                # Save the form with the provided start_date
                habit = form.save(commit=False)
                habit.user = request.user
                habit.start_date = start_date
                habit.save()

                # Create tasks with their due and start dates for the habit
                # to populate the Task table
                TaskTracker.create_tasks(habit)

                habit_name = form.cleaned_data.get('name')
                messages.success(request, f'{habit_name} Habit created')
                return redirect('habit-home')
        else:
            form = HabitForm()
        context = {
            'form': form, 
            'pre_defined_habits': pre_defined_habits
        }

        return render(request, 'add_habit.html', context)

    @staticmethod
    def delete_habit(request, habit_id):
        """
        Handles deleting a habit.

        Parameters
        ----------
        request : HttpRequest
            The HTTP request.
        habit_id : int
            The ID of the habit to delete.

        Returns
        -------
        HttpResponse
            The HTTP response.
        """
        if not request.user.is_authenticated:
            return redirect('login')
        
        habit = get_object_or_404(Habit, pk=habit_id)

        
        if request.method == 'POST':
            try:
                habit.delete()
                return redirect('active_habits')
            except Habit.DoesNotExist:
                pass            
        return render(request, 'habit_confirm_delete.html', {'habit': habit})
        
    @staticmethod
    def active_habits(request):
        """
        Displays active habits for the logged-in user.

        Parameters
        ----------
        request : HttpRequest
            The HTTP request.

        Returns
        -------
        HttpResponse
            The HTTP response.
        """
        if not request.user.is_authenticated:
            return redirect('login')
        
        user_id = request.user.id

        # Query all tracked habits with their longest streak and current streak
        all_active_habits = all_tracked_habits(user_id=user_id)

        # Filter tracked habits with the same periodicity
        daily_habits = habits_by_period('daily')(all_active_habits)
        weekly_habits = habits_by_period('weekly')(all_active_habits)
        monthly_habits = habits_by_period('monthly')(all_active_habits)

        # Calculate progress percentage for each active habit
        calculate_progress(all_active_habits)
        calculate_progress(daily_habits)
        calculate_progress(weekly_habits)
        calculate_progress(monthly_habits)

        context = {
            'active_habits': all_active_habits,
            'daily_habits': daily_habits,
            'weekly_habits': weekly_habits,
            'monthly_habits': monthly_habits,
        }
        return render(request, 'habit_manager.html', context)

    @staticmethod
    def habit_detail(request, habit_id):
        """
        Display detailed information about a habit:
        - task log
        - streak data
        - achievements
        - task counts

        This version recalculates streaks from actual completed/failed tasks
        before showing the page.
        """

        if not request.user.is_authenticated:
            return redirect('login')

        habit = get_object_or_404(Habit, pk=habit_id, user=request.user)

        tasks = TaskTracker.objects.filter(
            habit_id=habit_id
        ).order_by('task_number')

        # Recalculate streak from actual task statuses
        streak = Streak.sync_streak_with_tasks(habit_id)

        achievement = Achievement.objects.filter(
            habit_id=habit_id
        ).order_by('-date')

        num_inprogress_tasks(habit)

        completed_count = tasks.filter(task_status='Completed').count()
        failed_count = tasks.filter(task_status='Failed').count()
        in_progress_count = tasks.filter(task_status='In progress').count()

        total_finished_tasks = completed_count + failed_count

        if total_finished_tasks > 0:
            success_rate = round((completed_count / total_finished_tasks) * 100, 1)
        else:
            success_rate = 0

        context = {
            'habit': habit,
            'tasks': tasks,
            'streak': streak,
            'achievement': achievement,
            'completed_count': completed_count,
            'failed_count': failed_count,
            'in_progress_count': in_progress_count,
            'success_rate': success_rate,
            'total_tasks': tasks.count(),
        }

        return render(request, 'habit_details.html', context)


class HabitAnalysis(View):
    """
    View class for handling habit analysis and analytics dashboard.

    This class provides methods for displaying analytics and insights about user habits.

    Methods
    -------
    get(request, *args, **kwargs)
        Handles GET requests for habit analysis dashboard.
    post(request, *args, **kwargs)
        Handles POST requests for habit analysis.
    """
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """
        Handles GET requests for habit analysis dashboard.
        
        Displays analytics dashboard with charts and statistics about user habits.

        Parameters
        ----------
        request : HttpRequest
            The HTTP request.

        Returns
        -------
        HttpResponse
            Rendered analysis template with analytics data.
        """
        user = request.user
        user_id = user.id
        
        # Get all habits for the current user (active and completed)
        all_habits = all_tracked_habits(user_id=user_id)
        total_habits = all_habits.count()
        
        # Initialize data structures for charts
        habit_names = []
        completed_tasks_per_habit = []
        failed_tasks_per_habit = []
        current_streaks_list = []
        longest_streaks_list = []
        completion_percentages = []
        
        # Track for best/worst habits
        habit_completion_data = {}
        habit_streak_data = {}
        
        for habit in all_habits:
            habit_names.append(habit.name)
            
            # Get task statistics for this habit
            completed_tasks = TaskTracker.objects.filter(
                habit=habit, 
                task_status='Completed'
            ).count()
            
            failed_tasks = TaskTracker.objects.filter(
                habit=habit, 
                task_status='Failed'
            ).count()
            
            completed_tasks_per_habit.append(completed_tasks)
            failed_tasks_per_habit.append(failed_tasks)
            
            # Calculate completion percentage
            total_tasks = completed_tasks + failed_tasks
            if total_tasks > 0:
                completion_pct = round((completed_tasks / total_tasks) * 100, 1)
            else:
                completion_pct = 0
            completion_percentages.append(completion_pct)
            
            # Get streak information - sync first to ensure accuracy
            streak = Streak.sync_streak_with_tasks(habit.id)
            if streak:
                current_streak = streak.current_streak
                longest_streak = streak.longest_streak
            else:
                current_streak = 0
                longest_streak = 0
                
            current_streaks_list.append(current_streak)
            longest_streaks_list.append(longest_streak)
            
            # Store for best/worst calculations
            habit_completion_data[habit.name] = {
                'completed': completed_tasks,
                'failed': failed_tasks,
                'percentage': completion_pct,
                'total_tasks': total_tasks
            }
            
            habit_streak_data[habit.name] = {
                'current': current_streak,
                'longest': longest_streak
            }
        
        # Calculate overall statistics
        total_completed_tasks = TaskTracker.objects.filter(
            habit__user=user, 
            task_status='Completed'
        ).count()
        
        total_failed_tasks = TaskTracker.objects.filter(
            habit__user=user, 
            task_status='Failed'
        ).count()
        
        total_tasks_all = total_completed_tasks + total_failed_tasks
        
        if total_tasks_all > 0:
            overall_completion_percentage = round(
                (total_completed_tasks / total_tasks_all) * 100, 1
            )
        else:
            overall_completion_percentage = 0
        
        # Find best current streak
        best_current_streak = max(current_streaks_list) if current_streaks_list else 0
        
        # Find longest streak overall
        longest_streak_overall = max(longest_streaks_list) if longest_streaks_list else 0
        
        # Find most consistent habit (highest completion percentage with at least 3 tasks)
        consistent_habits = [
            (name, data['percentage']) 
            for name, data in habit_completion_data.items() 
            if data['total_tasks'] >= 3
        ]
        if consistent_habits:
            most_consistent_habit = max(consistent_habits, key=lambda x: x[1])[0]
            most_consistent_percentage = max([p for _, p in consistent_habits])
        else:
            most_consistent_habit = "N/A"
            most_consistent_percentage = 0
        
        # Find most struggled habit (highest failed count)
        struggled_habits = [
            (name, data['failed']) 
            for name, data in habit_completion_data.items()
        ]
        if struggled_habits and max([f for _, f in struggled_habits]) > 0:
            most_struggled_habit = max(struggled_habits, key=lambda x: x[1])[0]
            most_struggled_fails = max([f for _, f in struggled_habits])
        else:
            most_struggled_habit = "N/A"
            most_struggled_fails = 0
        
        # Prepare data for Chart.js - use json.dumps for safe rendering
        charts_data = {
            'habit_names': json.dumps(habit_names),
            'completed_tasks': json.dumps(completed_tasks_per_habit),
            'failed_tasks': json.dumps(failed_tasks_per_habit),
            'current_streaks': json.dumps(current_streaks_list),
            'longest_streaks': json.dumps(longest_streaks_list),
            'completion_percentages': json.dumps(completion_percentages),
        }
        
        # Keep existing analytics data for backward compatibility
        all_tracked = all_tracked_habits(user_id=user_id)
        daily_habits = habits_by_period('daily')(all_tracked)
        weekly_habits = habits_by_period('weekly')(all_tracked)
        monthly_habits = habits_by_period('monthly')(all_tracked)
        
        # Retrieve completed habits
        completed_habits = all_completed_habits(user_id)
        
        # Retrieve the habit with the current longest streak
        longest_current_all_streak = longest_current_streak_over_all_habits()
        
        # Retrieve the habit with longest streak
        longest_all_streak = longest_streak_over_all_habits()
        
        # Calculate progress for existing analytics
        calculate_progress(all_tracked)
        calculate_progress(daily_habits)
        calculate_progress(weekly_habits)
        calculate_progress(monthly_habits)
        calculate_progress(longest_all_streak)
        calculate_progress(longest_current_all_streak)
        
        # Weight configuration for rank_habits
        weights = {
            'completed_tasks': -0.2,
            'failed_tasks': 0.8,
            'longest_streak': -0.2,
            'current_streak': -0.1
        }
        
        daily_struggled_most = rank_habits(weights, 'daily')
        weekly_struggled_most = rank_habits(weights, 'weekly')
        
        context = {
            # New analytics dashboard data
            'charts_data': charts_data,
            'total_habits': total_habits,
            'total_completed_tasks': total_completed_tasks,
            'total_failed_tasks': total_failed_tasks,
            'overall_completion_percentage': overall_completion_percentage,
            'best_current_streak': best_current_streak,
            'longest_streak': longest_streak_overall,
            'most_consistent_habit': most_consistent_habit,
            'most_consistent_percentage': most_consistent_percentage,
            'most_struggled_habit': most_struggled_habit,
            'most_struggled_fails': most_struggled_fails,
            'has_habits': total_habits > 0,
            
            # Keep existing data for backward compatibility
            'all_habits': all_tracked,
            'daily_habits': daily_habits,
            'weekly_habits': weekly_habits,
            'monthly_habits': monthly_habits,
            'daily_struggled_most': daily_struggled_most,
            'weekly_struggled_most': weekly_struggled_most,
            'longest_all_streak': longest_all_streak,
            'longest_current_all_streak': longest_current_all_streak,
            'completed_habits': completed_habits
        }
        
        return render(request, 'analysis.html', context)

    def post(self, request, *args, **kwargs):
        """
        Handles POST requests for habit analysis.
        
        Retrieves selected habit data and its related streak information.

        Parameters
        ----------
        request : HttpRequest
            The HTTP request.

        Returns
        -------
        JsonResponse
            JSON response containing habit data with related streak information.
        """
        selected_value = request.POST.get('selectedValue')
        
        # Retrieve the habit object with related streak using prefetch_related
        habit = Habit.objects.prefetch_related('streak').get(id=selected_value)
        
        # Serialize the habit object along with related streak data
        habit_data = serializers.serialize('json', [habit])
        
        # Convert serialized data to Python dictionary
        habit_dict = json.loads(habit_data)[0]['fields']
        
        # Add streak data to habit dictionary
        habit_dict['streak'] = list(habit.streak.values())
        
        return JsonResponse(habit_dict, safe=False)


