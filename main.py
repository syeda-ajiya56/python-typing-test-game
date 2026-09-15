# app.py
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
import random
import json
import os
import pickle
from typing import Dict, List, Optional, Any

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this in production

# Load custom word lists from JSON file
def load_word_lists():
    with open('data/word_lists.json', 'r') as f:
        return json.load(f)

# Load achievements from JSON file
def load_achievements():
    try:
        with open('data/achievements.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        # Return default achievements if file doesn't exist
        return {
            "speed_demon": {
                "name": "Speed Demon",
                "description": "Reach 100 WPM in any game mode",
                "icon": "⚡",
                "requirement": 100,
                "type": "wpm"
            },
            "accuracy_master": {
                "name": "Accuracy Master",
                "description": "Complete a game with 100% accuracy",
                "icon": "🎯",
                "requirement": 100,
                "type": "accuracy"
            },
            "word_warrior": {
                "name": "Word Warrior",
                "description": "Type 1000 correct words",
                "icon": "⌨️",
                "requirement": 1000,
                "type": "total_words"
            }
        }

# Initialize data storage (in production, use a proper database)
users = {}
game_states = {}
leaderboards = {
    'classic': [],
    'time_attack': [],
    'word_count': []
}
active_multiplayer_games = {}

# Add practice session storage
practice_sessions: Dict[str, Dict] = {}

class GameMode:
    CLASSIC = 'classic'
    TIME_ATTACK = 'time_attack'
    WORD_COUNT = 'word_count'
    PRACTICE = 'practice'
    MULTIPLAYER = 'multiplayer'

class Achievement:
    def __init__(self, name, description, condition):
        self.name = name
        self.description = description
        self.condition = condition

    def check(self, stats):
        return self.condition(stats)

# Initialize achievements
achievements = [
    Achievement('Speed Demon', 'Reach 100 WPM', lambda stats: stats['max_wpm'] >= 100),
    Achievement('Marathon Runner', 'Complete 100 games', lambda stats: stats['games_played'] >= 100),
    Achievement('Perfect Game', 'Complete a game with 100% accuracy', lambda stats: stats['max_accuracy'] == 100),
    Achievement('Multiplayer Master', 'Win 10 multiplayer games', lambda stats: stats['multiplayer_wins'] >= 10),
]

def calculate_wpm(start_time, words_typed):
    elapsed_time = datetime.now() - start_time
    minutes = elapsed_time.total_seconds() / 10
    return int(words_typed / minutes) if minutes > 0 else 0

def calculate_accuracy(correct_words, total_words):
    return int((correct_words / total_words * 100) if total_words > 0 else 100)

def update_achievements(username):
    user = users[username]
    new_achievements = []
    
    for achievement in achievements:
        if achievement.name not in user['achievements'] and achievement.check(user['stats']):
            user['achievements'].append(achievement.name)
            new_achievements.append(achievement.name)
    
    return new_achievements

# Initialize users dictionary with persistence
def load_users():
    try:
        with open('data/users.pkl', 'rb') as f:
            return pickle.load(f)
    except (FileNotFoundError, EOFError):
        return {}

def save_users():
    os.makedirs('data', exist_ok=True)
    with open('data/users.pkl', 'wb') as f:
        pickle.dump(users, f)

# Initialize users at startup
users = load_users()

@app.route('/')
def index():
    if 'username' not in session:
        return render_template('index.html')
    return redirect(url_for('game_modes'))

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    password = request.form.get('password')

    if not username or not password:
        flash('Please fill in all fields.')
        return redirect(url_for('index'))

    if username in users:
        flash('Username already exists.')
        return redirect(url_for('index'))

    # Initialize user with all required fields
    users[username] = {
        'password': password,
        'stats': {
            'games_played': 0,
            'total_words': 0,
            'correct_words': 0,
            'high_score': 0,
            'max_wpm': 0,
            'max_accuracy': 0,
            'multiplayer_games': 0,
            'multiplayer_wins': 0
        },
        'achievements': []
    }
    
    save_users()  # Save after registration
    
    flash('Registration successful! Please log in.')
    return redirect(url_for('index'))


@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')

    if username in users and users[username]['password'] == password:
        session['username'] = username
        return redirect(url_for('game_modes'))

    flash('Invalid credentials.')
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('Logged out successfully.')
    return redirect(url_for('index'))

@app.route('/game_modes')
def game_modes():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    # Filter only waiting games
    active_games = {
        game_id: game 
        for game_id, game in active_multiplayer_games.items() 
        if game['state'] == 'waiting'
    }
    
    return render_template('game_modes.html', active_games=active_games)

@app.route('/practice')
def practice():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    # Clear any existing practice session
    if 'practice' in session:
        session.pop('practice')
    
    return render_template('practice.html',
                         word_lists=load_word_lists(),
                         practice_active=False)

@app.route('/multiplayer/create')
def create_multiplayer():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    # Clean up old games
    current_time = datetime.now()
    for game_id in list(active_multiplayer_games.keys()):
        game = active_multiplayer_games[game_id]
        if ('start_time' in game and 
            (current_time - game['start_time']).total_seconds() > 3600):  # Remove games older than 1 hour
            active_multiplayer_games.pop(game_id)
    
    word_lists = load_word_lists()
    all_words = (word_lists['easy'] + 
                 word_lists['medium'] + 
                 word_lists['hard'])
    
    game_id = str(random.randint(1000, 9999))
    while game_id in active_multiplayer_games:  # Ensure unique game ID
        game_id = str(random.randint(1000, 9999))
    
    game = {
        'creator': session['username'],
        'players': [session['username']],
        'state': 'waiting',
        'words': random.sample(all_words, min(20, len(all_words))),
        'start_time': None,
        'scores': {}
    }
    active_multiplayer_games[game_id] = game
    
    return render_template('multiplayer_lobby.html', 
                         game_id=game_id,
                         game=game)

@app.route('/multiplayer/join', methods=['POST'])
def join_multiplayer():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    game_id = request.form.get('game_id')
    if not game_id or game_id not in active_multiplayer_games:
        flash('Game not found.')
        return redirect(url_for('game_modes'))
    
    game = active_multiplayer_games[game_id]
    if game['state'] != 'waiting':
        flash('Game already in progress.')
        return redirect(url_for('game_modes'))
    
    if session['username'] not in game['players']:
        game['players'].append(session['username'])
    
    return render_template('multiplayer_lobby.html', 
                         game_id=game_id,
                         game=game)

@app.route('/leaderboards')
def leaderboards_view():
    return render_template('leaderboards.html', leaderboards=leaderboards)

@app.route('/stats')
def stats():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    username = session['username']
    if username not in users:
        flash('User data not found. Please log in again.')
        return redirect(url_for('logout'))
    
    user_stats = users[username]['stats']
    achievements_data = load_achievements()
    earned_achievements = users[username].get('achievements', [])
    
    # Calculate achievement progress
    achievements_progress = []
    
    for achievement in achievements_data.values():
        achievement_type = achievement.get('type')
        if achievement_type == 'wpm':
            current = user_stats.get('max_wpm', 0)
        elif achievement_type == 'accuracy':
            current = user_stats.get('max_accuracy', 0)
        elif achievement_type == 'total_words':
            current = user_stats.get('correct_words', 0)
        elif achievement_type == 'avg_accuracy':
            total_words = user_stats.get('total_words', 0)
            current = round(user_stats.get('correct_words', 0) / total_words * 100, 1) if total_words else 0
        elif achievement_type == 'games':
            current = user_stats.get('games_played', 0)
        elif achievement_type == 'multiplayer_wins':
            current = user_stats.get('multiplayer_wins', 0)
        else:
            current = 0

        threshold = achievement.get('requirement', 0)
        achievements_progress.append({
            'name': achievement['name'],
            'description': achievement['description'],
            'icon': achievement.get('icon', ''),
            'current': current,
            'requirement': threshold,
            'earned': achievement['name'] in earned_achievements,
            'percentage': min(100, int((current / threshold) * 100)) if threshold else 0
        })
    
    return render_template('stats.html',
                         stats=user_stats,
                         achievements=achievements_progress)

def update_achievements(username):
    """Update user achievements based on their current stats"""
    if username not in users:
        return []
    
    user = users[username]
    stats = user['stats']
    achievements_data = load_achievements()
    earned = user.get('achievements', [])
    new_achievements = []
    
    for achievement in achievements_data.values():
        if achievement['name'] in earned:
            continue

        achievement_type = achievement.get('type')
        if achievement_type == 'wpm':
            current = stats.get('max_wpm', 0)
        elif achievement_type == 'accuracy':
            current = stats.get('max_accuracy', 0)
        elif achievement_type == 'total_words':
            current = stats.get('correct_words', 0)
        elif achievement_type == 'games':
            current = stats.get('games_played', 0)
        elif achievement_type == 'multiplayer_wins':
            current = stats.get('multiplayer_wins', 0)
        else:
            current = 0

        if current >= achievement.get('requirement', 0):
            new_achievements.append(achievement['name'])
    
    # Add new achievements to user's earned list
    if new_achievements:
        user['achievements'].extend(new_achievements)
        save_users()
    
    return new_achievements

@app.route('/reset_stats', methods=['POST'])
def reset_stats():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    username = session['username']
    if username not in users:
        flash('User data not found. Please log in again.')
        return redirect(url_for('logout'))
    
    # Reset stats to initial values
    users[username]['stats'] = {
        'games_played': 0,
        'total_words': 0,
        'correct_words': 0,
        'high_score': 0,
        'max_wpm': 0,
        'max_accuracy': 0,
        'multiplayer_games': 0,
        'multiplayer_wins': 0
    }
    # Keep achievements but clear them
    users[username]['achievements'] = []
    
    save_users()  # Save the reset stats
    flash('Statistics have been reset successfully!')
    return redirect(url_for('stats'))

# More routes and game logic will be added here...
# routes.py (append to app.py)

@app.route('/game/<mode>')
def game(mode):
    if 'username' not in session:
        return redirect(url_for('index'))
    
    game_id = str(random.randint(1000000, 9999999))
    word_lists = load_word_lists()
    all_words = word_lists['easy'] + word_lists['medium'] + word_lists['hard']
    
    # Set word count based on mode, but ensure it doesn't exceed available words
    word_count = min(len(all_words), {
        'classic': 19,
        'time_attack': 14,
        'word_count': 49
    }.get(mode, 20))
    
    # Ensure we have enough words by repeating the list if necessary
    if len(all_words) < word_count:
        # Repeat the word list until we have enough words
        multiplier = (word_count // len(all_words)) + 1
        all_words = all_words * multiplier
    
    # Initialize game state
    game_state = {
        'mode': mode,
        'words': random.sample(all_words, word_count),
        'current_index': 0,
        'start_time': datetime.now()
    }
    
    # Set initial time based on mode
    time_left = {
        'classic': 30,      # 30 seconds for 20 words
        'time_attack': 10,  # 10 seconds for 15 words
        'word_count': 0     # Stopwatch mode for 50 words
    }.get(mode, 30)
    
    game_states[game_id] = game_state
    
    template_vars = {
        'mode': mode,
        'game_id': game_id,
        'current_word': game_state['words'][0],
        'time_left': time_left,
        'total_words': word_count
    }
    
    return render_template('game.html', **template_vars)

@app.route('/submit_word', methods=['POST'])
def submit_word():
    game_id = request.form.get('game_id')
    typed_word = request.form.get('typed_word', '').strip()
    
    if game_id not in game_states:
        return jsonify({'error': 'Invalid game'}), 400
    
    game_state = game_states[game_id]
    current_word = game_state['words'][game_state['current_index']]
    is_correct = typed_word.lower() == current_word.lower()
    
    # Update user stats for word tracking
    username = session['username']
    if username in users:
        users[username]['stats']['total_words'] += 1
        if is_correct:
            users[username]['stats']['correct_words'] += 1
        save_users()
    
    # Move to next word
    game_state['current_index'] += 1
    game_over = game_state['current_index'] >= len(game_state['words'])
    
    next_word = (game_state['words'][game_state['current_index']] 
                 if not game_over else '')
    
    return jsonify({
        'correct': is_correct,
        'next_word': next_word,
        'game_over': game_over
    })

@app.route('/game_over', methods=['POST'])
def game_over():
    game_id = request.form.get('game_id')
    wpm = int(request.form.get('wpm', 0))
    accuracy = int(request.form.get('accuracy', 0))
    
    if game_id in game_states:
        game_state = game_states.pop(game_id)  # Remove game state
        
        # Save stats to user profile
        username = session['username']
        if username in users:
            users[username]['stats']['games_played'] += 1
            users[username]['stats']['max_wpm'] = max(users[username]['stats']['max_wpm'], wpm)
            users[username]['stats']['max_accuracy'] = max(users[username]['stats']['max_accuracy'], accuracy)
            save_users()  # Save updated stats
    
    return jsonify({'redirect_url': url_for('stats')})

# Multiplayer functionality
@app.route('/multiplayer/start', methods=['POST'])
def start_multiplayer():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    game_id = request.form.get('game_id')
    if not game_id or game_id not in active_multiplayer_games:
        flash('Game not found.')
        return redirect(url_for('game_modes'))
    
    game = active_multiplayer_games[game_id]
    if game['creator'] != session['username']:
        flash('Only the creator can start the game.')
        return redirect(url_for('game_modes'))
    
    game['state'] = 'in_progress'
    game['start_time'] = datetime.now()
    
    return render_template('game.html',
                         game_id=game_id,
                         mode='multiplayer',
                         current_word=game['words'][0],
                         words_left=len(game['words']))

@app.route('/multiplayer/update/<game_id>', methods=['POST'])
def update_multiplayer_game(game_id):
    if game_id not in active_multiplayer_games:
        return redirect(url_for('game_modes'))
    
    game = active_multiplayer_games[game_id]
    typed_word = request.form.get('typed_word').strip()
    player = session['username']
    
    current_word_index = game['player_stats'][player]['words_completed']
    if current_word_index >= len(game['words']):
        return jsonify({'game_over': True})
    
    if typed_word == game['words'][current_word_index]:
        game['player_stats'][player]['words_completed'] += 1
    
    # Check if any player has won
    if game['player_stats'][player]['words_completed'] >= len(game['words']):
        return end_multiplayer_game(game_id, player)
    
    return jsonify(game['player_stats'])

def end_multiplayer_game(game_id, winner):
    game = active_multiplayer_games[game_id]
    
    # Update stats for all players
    for player in game['players']:
        users[player]['stats']['multiplayer_games'] += 1
        if player == winner:
            users[player]['stats']['multiplayer_wins'] += 1
    
    # Clean up game
    del active_multiplayer_games[game_id]
    
    return render_template('multiplayer_results.html',
                         winner=winner,
                         stats=game['player_stats'])

@app.route('/practice/submit', methods=['POST'])
def submit_practice_word():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    typed_word = request.form.get('typed_word', '').strip()
    practice_state = session.get('practice')
    
    if not practice_state:
        return redirect(url_for('practice'))
    
    current_word = practice_state['words'][practice_state['current_index']]
    practice_state['words_completed'] += 1
    
    if typed_word == current_word:
        practice_state['correct_words'] += 1
    
    practice_state['current_index'] += 1
    
    # Check if we've reached the end of the word list
    if practice_state['current_index'] >= len(practice_state['words']):
        practice_state['current_index'] = 0  # Loop back to beginning
    
    # Calculate accuracy
    accuracy = (practice_state['correct_words'] / practice_state['words_completed'] * 100) if practice_state['words_completed'] > 0 else 100
    
    # Update session
    session['practice'] = practice_state
    
    return render_template('practice.html',
                         word_lists=load_word_lists(),
                         practice_active=True,
                         current_word=practice_state['words'][practice_state['current_index']],
                         words_completed=practice_state['words_completed'],
                         accuracy=round(accuracy, 1))

@app.route('/practice/start', methods=['POST'])
def start_practice():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    word_list = request.form.get('word_list')
    word_lists = load_word_lists()
    
    if word_list.startswith('custom_'):
        list_name = word_list[7:]  # Remove 'custom_' prefix
        practice_words = word_lists['custom_lists'][list_name]
    else:
        practice_words = word_lists[word_list]
    
    # Initialize practice session
    session['practice'] = {
        'words': practice_words,
        'current_index': 0,
        'words_completed': 0,
        'correct_words': 0
    }
    
    return render_template('practice.html',
                         word_lists=word_lists,
                         practice_active=True,
                         current_word=practice_words[0],
                         words_completed=0,
                         accuracy=100)

# Add session checking to all protected routes
@app.before_request
def check_session():
    protected_routes = ['game_modes', 'game', 'practice', 'stats', 'submit_word']
    if (request.endpoint in protected_routes and 
        'username' in session and 
        session['username'] not in users):
        session.clear()
        flash('Session expired. Please login again.')
        return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)