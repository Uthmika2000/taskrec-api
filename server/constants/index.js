// Parse a numeric env var, falling back to a default when unset/invalid.
const num = (v, d) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : d;
};

module.exports = {
  AUTH: {
    TOKEN_EXPIRY: '24h',
    COOKIE_MAX_AGE: 24 * 60 * 60 * 1000,
    PASSWORD_MIN_LENGTH: 6,
  },

  ROLES: {
    ADMIN: 'admin',
    SCRUM_MASTER: 'scrum_master',
    DEVELOPER: 'developer',
  },

  TASK: {
    TYPES:    ['USER_STORY', 'BUG', 'TASK', 'SUBTASK'],
    STATUSES: ['TO_DO', 'IN_PROGRESS', 'DONE'],
    PRIORITIES: ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'],
    DEFAULT_TYPE:         'TASK',
    DEFAULT_STATUS:       'TO_DO',
    DEFAULT_PRIORITY:     'MEDIUM',
    DEFAULT_STORY_POINTS: 1,
  },

  SPRINT: {
    STATUSES:           ['PLANNING', 'ACTIVE', 'COMPLETED'],
    DEFAULT_STATUS:     'PLANNING',
    DEFAULT_CAPACITY:   40,
    CLONE_DURATION_DAYS: 14,
  },

  FEEDBACK: {
    ACTIONS: ['accept', 'reject'],
  },

  NOTIFICATION: {
    TYPES:    ['team_invite', 'system'],
    STATUSES: ['pending', 'accepted', 'rejected', 'read'],
  },

  ML: {
    TIMEOUT_RECOMMEND: 10000,
    TIMEOUT_FEEDBACK:  5000,
    TIMEOUT_ACCURACY:  5000,
    TOP_RECOMMENDATIONS: 3,
    WEIGHTS: {
      NLP:        num(process.env.ML_W_NLP, 0.4),
      CF:         num(process.env.ML_W_CF,  0.4),
      CAPACITY:   num(process.env.ML_W_CAP, 0.2),
      CF_NEUTRAL: 0.5,
    },
  },

  PREFERENCES_DEFAULTS: {
    themeMode:           'system',
    fontSize:            14,
    compactMode:         false,
    reducedMotion:       false,
    emailNotifications:  true,
    pushNotifications:   true,
    notificationSound:   true,
    weeklyDigest:        true,
    sprintAlerts:        true,
    assignmentAlerts:    true,
    mlSuggestions:       true,
    accentColor:         'indigo',
  },
};