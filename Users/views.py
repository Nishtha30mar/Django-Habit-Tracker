from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .forms import UserRegisterForm
from habit.models import Habit, TaskTracker, Streak
from django.db.models import Max
from django.utils import timezone

def register(request):
    """
    View function for user registration.
    """
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}')
            return redirect('login')
    else:
        form = UserRegisterForm()
    return render(request, 'Users/register.html', {'form': form})


@login_required
def profile(request):
    """
    Display user profile with habit statistics and edit functionality.
    """
    user = request.user
    
    # Handle profile update
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        
        # Update user's first and last name
        user.first_name = first_name
        user.last_name = last_name
        user.save()
        
        messages.success(request, 'Your profile has been updated successfully!')
        return redirect('profile')
    
    # Calculate habit statistics
    total_habits = Habit.objects.filter(user=user).count()
    
    # Active habits (where completion date is in the future)
    active_habits = Habit.objects.filter(user=user, completion_date__gte=timezone.now()).count()
    
    # Completed habits (all tasks marked as 'Completed')
    completed_habits_count = 0
    all_habits = Habit.objects.filter(user=user)
    for habit in all_habits:
        total_tasks = TaskTracker.objects.filter(habit=habit).count()
        completed_tasks = TaskTracker.objects.filter(habit=habit, task_status='Completed').count()
        if total_tasks > 0 and completed_tasks == total_tasks:
            completed_habits_count += 1
    
    # Failed habits count (habits with at least one failed task)
    failed_habits_count = 0
    for habit in all_habits:
        failed_tasks = TaskTracker.objects.filter(habit=habit, task_status='Failed').count()
        if failed_tasks > 0:
            failed_habits_count += 1
    
    # Get current streak (best current streak across all habits)
    current_streak = Streak.objects.filter(habit__user=user).aggregate(Max('current_streak'))['current_streak__max'] or 0
    
    # Get longest streak ever
    longest_streak = Streak.objects.filter(habit__user=user).aggregate(Max('longest_streak'))['longest_streak__max'] or 0
    
    # Total tasks completed across all habits
    total_completed_tasks = TaskTracker.objects.filter(habit__user=user, task_status='Completed').count()
    
    # Total tasks failed across all habits
    total_failed_tasks = TaskTracker.objects.filter(habit__user=user, task_status='Failed').count()
    
    context = {
        'total_habits': total_habits,
        'active_habits_count': active_habits,
        'completed_habits_count': completed_habits_count,
        'failed_habits_count': failed_habits_count,
        'current_streak': current_streak,
        'longest_streak': longest_streak,
        'total_completed_tasks': total_completed_tasks,
        'total_failed_tasks': total_failed_tasks,
    }
    
    return render(request, 'Users/profile.html', context)