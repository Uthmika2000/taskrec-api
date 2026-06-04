const express = require('express');
const router = express.Router();
const User = require('../models/User');
const Team = require('../models/Team');
const Sprint = require('../models/Sprint');
const Assignment = require('../models/Assignment');
const Feedback = require('../models/Feedback');
const { authMiddleware, requireRole } = require('../middleware/authMiddleware');

// ─── GET /api/settings/user ─────────────────────────────────────────────────────
router.get('/user', authMiddleware, async (req, res, next) => {
  try {
    const user = await User.findById(req.user._id)
      .select('-passwordHash')
      .populate('teamIds', 'name');

    res.json({
      success: true,
      data: {
        user,
        stats: {
          totalTasks: await require('../models/Task').countDocuments({ createdBy: req.user._id }),
          totalSprints: await Sprint.countDocuments({ teamId: { $in: req.user.teamIds } }),
          totalAssignments: await Assignment.countDocuments({ developerId: req.user._id }),
          feedbackGiven: await Feedback.countDocuments({ developerId: req.user._id }),
        },
      },
    });
  } catch (error) {
    next(error);
  }
});

// ─── PATCH /api/settings/user ───────────────────────────────────────────────────
router.patch('/user', authMiddleware, async (req, res, next) => {
  try {
    const allowed = ['name', 'skillTags'];
    const updates = {};
    allowed.forEach(field => {
      if (req.body[field] !== undefined) updates[field] = req.body[field];
    });

    const user = await User.findByIdAndUpdate(
      req.user._id,
      updates,
      { new: true, runValidators: true }
    ).select('-passwordHash');

    res.json({ success: true, data: user });
  } catch (error) {
    next(error);
  }
});

// ─── PUT /api/settings/password ───────────────────────────────────────────────
router.put('/password', authMiddleware, async (req, res, next) => {
  try {
    const { currentPassword, newPassword } = req.body;

    if (!currentPassword || !newPassword) {
      return res.status(400).json({ success: false, message: 'Both passwords are required.' });
    }

    if (newPassword.length < 6) {
      return res.status(400).json({ success: false, message: 'New password must be at least 6 characters.' });
    }

    const user = await User.findById(req.user._id);
    const isMatch = await user.comparePassword(currentPassword);
    if (!isMatch) {
      return res.status(400).json({ success: false, message: 'Current password is incorrect.' });
    }

    user.passwordHash = newPassword; // Will be hashed by pre-save hook
    await user.save();

    res.json({ success: true, message: 'Password updated successfully.' });
  } catch (error) {
    next(error);
  }
});

// ─── POST /api/settings/export ──────────────────────────────────────────────────
router.post('/export', authMiddleware, async (req, res, next) => {
  try {
    const userId = req.user._id;

    const user = await User.findById(userId).select('-passwordHash');
    const tasks = await require('../models/Task').find({ createdBy: userId });
    const assignments = await Assignment.find({ developerId: userId });
    const feedback = await Feedback.find({ developerId: userId });
    const teams = await Team.find({ memberIds: userId });

    const exportData = {
      exportedAt: new Date().toISOString(),
      user: {
        name: user.name,
        email: user.email,
        role: user.role,
        skillTags: user.skillTags,
        createdAt: user.createdAt,
      },
      tasks: tasks.map(t => ({
        title: t.title,
        description: t.description,
        storyPoints: t.storyPoints,
        priority: t.priority,
        status: t.status,
        createdAt: t.createdAt,
      })),
      assignments: assignments.map(a => ({
        taskId: a.taskId,
        accepted: a.accepted,
        createdAt: a.createdAt,
      })),
      feedback: feedback.map(f => ({
        action: f.action,
        createdAt: f.createdAt,
      })),
      teams: teams.map(t => ({ name: t.name, createdAt: t.createdAt })),
    };

    res.json({ success: true, data: exportData });
  } catch (error) {
    next(error);
  }
});

// ─── DELETE /api/settings/account ──────────────────────────────────────────────
router.delete('/account', authMiddleware, async (req, res, next) => {
  try {
    const userId = req.user._id;
    const { confirmEmail } = req.body;

    if (confirmEmail !== req.user.email) {
      return res.status(400).json({ success: false, message: 'Email confirmation required.' });
    }

    // Delete user's feedback
    await Feedback.deleteMany({ developerId: userId });
    // Delete user's assignments
    await Assignment.deleteMany({ developerId: userId });
    // Unassign tasks created by user
    await require('../models/Task').updateMany(
      { assigneeId: userId },
      { assigneeId: null }
    );
    // Remove from teams
    await Team.updateMany(
      { memberIds: userId },
      { $pull: { memberIds: userId } }
    );
    // Delete user
    await User.findByIdAndDelete(userId);

    res.clearCookie('token');
    res.json({ success: true, message: 'Account deleted permanently.' });
  } catch (error) {
    next(error);
  }
});

// ─── GET /api/settings/preferences ─────────────────────────────────────────────
router.get('/preferences', authMiddleware, async (req, res, next) => {
  try {
    const prefs = req.user.preferences || {
      themeMode: 'system',
      fontSize: 14,
      compactMode: false,
      reducedMotion: false,
      emailNotifications: true,
      pushNotifications: true,
      notificationSound: true,
      weeklyDigest: true,
      sprintAlerts: true,
      assignmentAlerts: true,
      mlSuggestions: true,
      accentColor: 'indigo',
    };

    res.json({ success: true, data: prefs });
  } catch (error) {
    next(error);
  }
});

// ─── PUT /api/settings/preferences ─────────────────────────────────────────────
router.put('/preferences', authMiddleware, async (req, res, next) => {
  try {
    const allowed = [
      'themeMode', 'fontSize', 'compactMode', 'reducedMotion',
      'emailNotifications', 'pushNotifications', 'notificationSound',
      'weeklyDigest', 'sprintAlerts', 'assignmentAlerts', 'mlSuggestions',
      'accentColor', 'autoSave', 'autoSaveInterval', 'dataRetention',
    ];

    const updates = {};
    allowed.forEach(field => {
      if (req.body[field] !== undefined) updates[field] = req.body[field];
    });

    const user = await User.findByIdAndUpdate(
      req.user._id,
      { preferences: updates },
      { new: true, runValidators: true }
    ).select('-passwordHash');

    res.json({ success: true, data: user.preferences });
  } catch (error) {
    next(error);
  }
});

// ─── GET /api/settings/stats ──────────────────────────────────────────────────
router.get('/stats', authMiddleware, async (req, res, next) => {
  try {
    const userId = req.user._id;

    const tasksCreated = await require('../models/Task').countDocuments({ createdBy: userId });
    const tasksAssigned = await require('../models/Task').countDocuments({ assigneeId: userId });
    const assignments = await Assignment.find({ developerId: userId });
    const feedbackGiven = await Feedback.countDocuments({ developerId: userId });

    const accepted = assignments.filter(a => a.accepted).length;
    const total = assignments.length;
    const acceptanceRate = total > 0 ? Math.round((accepted / total) * 100) : 0;

    res.json({
      success: true,
      data: {
        tasksCreated,
        tasksAssigned,
        totalAssignments: total,
        acceptanceRate,
        feedbackGiven,
        modelAccuracy: 0.72, // Simulated for demo
        giniScore: 0.18,   // Simulated
      },
    });
  } catch (error) {
    next(error);
  }
});

// ─── POST /api/settings/reset ──────────────────────────────────────────────────
router.post('/reset', authMiddleware, async (req, res, next) => {
  try {
    const user = await User.findByIdAndUpdate(
      req.user._id,
      {
        preferences: {
          themeMode: 'system',
          fontSize: 14,
          compactMode: false,
          reducedMotion: false,
          emailNotifications: true,
          pushNotifications: true,
          notificationSound: true,
          weeklyDigest: true,
          sprintAlerts: true,
          assignmentAlerts: true,
          mlSuggestions: true,
          accentColor: 'indigo',
        },
      },
      { new: true }
    ).select('-passwordHash');

    res.json({ success: true, data: user.preferences });
  } catch (error) {
    next(error);
  }
});

module.exports = router;