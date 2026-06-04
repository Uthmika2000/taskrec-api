const express = require('express');
const router = express.Router();
const axios = require('axios');
const Task = require('../models/Task');
const Sprint = require('../models/Sprint');
const Assignment = require('../models/Assignment');
const Feedback = require('../models/Feedback');
const { authMiddleware } = require('../middleware/authMiddleware');

// ── Gini coefficient ─────────────────────────────────────────────────────────
function giniCoefficient(values) {
  if (!values || values.length === 0) return 0;
  const n = values.length;
  const sorted = [...values].sort((a, b) => a - b);
  const sum = sorted.reduce((acc, v) => acc + v, 0);
  if (sum === 0) return 0;
  let numerator = 0;
  for (let i = 0; i < n; i++) {
    numerator += (2 * (i + 1) - n - 1) * sorted[i];
  }
  return Math.max(0, Math.min(1, numerator / (n * sum)));
}

// ── GET /api/metrics/workload/:sprintId ──────────────────────────────────────
// Used by MetricsPage workload tab and metrics_test.js
// Returns: { workloads[], giniCoefficient, totalTasks, totalPoints }
router.get('/workload/:sprintId', authMiddleware, async (req, res, next) => {
  try {
    const { sprintId } = req.params;

    // Verify the sprint exists so we can return a proper 404
    const sprint = await Sprint.findById(sprintId).select('_id capacityPoints teamId');
    if (!sprint) {
      return res.status(404).json({ success: false, message: 'Sprint not found.' });
    }

    const tasks = await Task.find({ sprintId })
      .populate('assigneeId', 'name email role skillTags');

    // Also load ALL team members so developers with 0 assigned tasks are included.
    // This gives an accurate Gini — excluding zero-point devs would hide inequality.
    const Team = require('../models/Team');
    const User = require('../models/User');
    const teamDoc = await Team.findById(sprint.teamId).select('memberIds');
    const allDevIds = teamDoc?.memberIds || [];
    const allDevs = await User.find({
      _id: { $in: allDevIds },
      role: 'developer',
    }).select('name email role skillTags');

    // Build workload map from tasks
    const developerMap = {};

    // Initialise every developer with 0 points first
    allDevs.forEach(dev => {
      developerMap[dev._id.toString()] = {
        developer: dev,
        points: 0,
        tasks: [],
        taskCount: 0,
      };
    });

    // Add task points for assigned developers
    tasks.forEach(task => {
      if (!task.assigneeId) return;
      const devId = task.assigneeId._id.toString();
      // Developer may not be in the team list (edge case) — add them anyway
      if (!developerMap[devId]) {
        developerMap[devId] = {
          developer: task.assigneeId,
          points: 0,
          tasks: [],
          taskCount: 0,
        };
      }
      developerMap[devId].points += task.storyPoints || 0;
      developerMap[devId].tasks.push({
        _id: task._id,
        title: task.title,
        storyPoints: task.storyPoints || 0,
        status: task.status,
        priority: task.priority,
      });
      developerMap[devId].taskCount += 1;
    });

    const workloads = Object.values(developerMap);
    const gini = giniCoefficient(workloads.map(w => w.points));
    const sprintCapacity = sprint.capacityPoints || 40;

    // Add capacity utilisation per developer
    workloads.forEach(w => {
      w.capacityPct = Math.round((w.points / sprintCapacity) * 100);
    });

    return res.json({
      success: true,
      data: {
        workloads,
        giniCoefficient: gini,
        totalTasks: tasks.length,
        totalPoints: tasks.reduce((s, t) => s + (t.storyPoints || 0), 0),
        sprintCapacity,
      },
    });
  } catch (error) {
    next(error);
  }
});

// ── GET /api/metrics/accuracy ────────────────────────────────────────────────
// MetricsPage calls metricsAPI.getAccuracy() → this endpoint.
// Tries the ML service first (/accuracy); if unavailable, computes from
// Feedback collection so numbers reflect real accept/reject data, not a
// hardcoded constant.
//
// ML service AccuracyResponse: { precision, recall, totalFeedback }
// This endpoint adds f1 and returns: { precision, recall, f1, totalFeedback }
router.get('/accuracy', authMiddleware, async (req, res, next) => {
  const mlServiceUrl = process.env.ML_SERVICE_URL || 'http://localhost:8000';

  try {
    // Try the real ML service first
    const mlRes = await axios.get(`${mlServiceUrl}/accuracy`, { timeout: 5000 });
    const { precision, recall, totalFeedback } = mlRes.data;
    const f1 =
      precision + recall > 0
        ? (2 * precision * recall) / (precision + recall)
        : 0;

    return res.json({
      success: true,
      data: {
        precision,
        recall,
        f1: Math.round(f1 * 10000) / 10000,
        totalFeedback,
        source: 'ml_service',
      },
    });
  } catch (mlError) {
    // ML service down — derive from real Feedback collection
    // Precision proxy: accepted / total feedback
    // Recall proxy: same (symmetric when using binary accept/reject)
    try {
      const [totalFeedback, acceptedFeedback] = await Promise.all([
        Feedback.countDocuments(),
        Feedback.countDocuments({ action: 'accept' }),
      ]);

      const precision = totalFeedback > 0 ? acceptedFeedback / totalFeedback : 0;
      const recall = precision; // proxy — real recall requires ranked-list evaluation
      const f1 =
        precision + recall > 0
          ? (2 * precision * recall) / (precision + recall)
          : 0;

      return res.json({
        success: true,
        data: {
          precision: Math.round(precision * 10000) / 10000,
          recall: Math.round(recall * 10000) / 10000,
          f1: Math.round(f1 * 10000) / 10000,
          totalFeedback,
          source: 'feedback_proxy',
          warning: 'ML service unavailable — metrics derived from feedback acceptance rate',
        },
      });
    } catch (dbError) {
      next(dbError);
    }
  }
});

// ── GET /api/metrics/evaluation ──────────────────────────────────────────────
// MetricsPage evaluation tab calls metricsAPI.getEvaluation().
// Uses real Feedback + Assignment data — no Math.random() simulation.
// Avoids .populate() so it works regardless of Feedback schema ref definitions.
// Returns: { precision, recall, f1, totalSamples, byDeveloper[], byDay{} }
router.get('/evaluation', authMiddleware, async (req, res, next) => {
  try {
    // ── Step 1: Count feedback by action ────────────────────────────────────
    // Use countDocuments so we never crash on missing refs or missing fields.
    // The Feedback schema created by feedback.js uses { action, taskId, developerId }
    // but field types vary — avoid populate() entirely.
    const [totalFeedback, acceptedFeedback] = await Promise.all([
      Feedback.countDocuments(),
      Feedback.countDocuments({ action: 'accept' }),
    ]);

    if (totalFeedback === 0) {
      return res.json({
        success: true,
        data: {
          precision: 0,
          recall: 0,
          f1: 0,
          totalSamples: 0,
          byDeveloper: [],
          byDay: {},
        },
      });
    }

    const precision = acceptedFeedback / totalFeedback;
    const recall = precision; // symmetric binary proxy
    const f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0;

    // ── Step 2: Per-developer breakdown ─────────────────────────────────────
    // Use MongoDB aggregation — no populate, no schema ref dependency.
    const devAgg = await Feedback.aggregate([
      {
        $group: {
          _id: '$developerId',
          total:    { $sum: 1 },
          accepted: { $sum: { $cond: [{ $eq: ['$action', 'accept'] }, 1, 0] } },
        },
      },
      { $sort: { total: -1 } },
    ]);

    // Look up developer names from User collection
    const User = require('../models/User');
    const devIds = devAgg.map(d => d._id).filter(Boolean);
    const users = await User.find({ _id: { $in: devIds } }).select('name email skillTags');
    const userMap = {};
    users.forEach(u => { userMap[u._id.toString()] = u; });

    const byDeveloper = devAgg.map(d => {
      const devId = d._id ? d._id.toString() : null;
      const user = devId ? userMap[devId] : null;
      const rate = d.total > 0 ? Math.round((d.accepted / d.total) * 10000) / 10000 : 0;
      return {
        developer: user
          ? { _id: user._id, name: user.name, email: user.email, skillTags: user.skillTags || [] }
          : { _id: devId, name: 'Unknown', email: '', skillTags: [] },
        accepted: d.accepted,
        total: d.total,
        rate,
      };
    });

    // ── Step 3: Daily breakdown for the line chart ───────────────────────────
    // Use $dateToString so we never call .toISOString() on a JS object in Node
    // (which crashes when createdAt is undefined on old records).
    const dayAgg = await Feedback.aggregate([
      {
        $match: { createdAt: { $exists: true, $ne: null } },
      },
      {
        $group: {
          _id: {
            $dateToString: { format: '%Y-%m-%d', date: '$createdAt' },
          },
          total:    { $sum: 1 },
          accepted: { $sum: { $cond: [{ $eq: ['$action', 'accept'] }, 1, 0] } },
        },
      },
      { $sort: { _id: 1 } },
    ]);

    const byDay = {};
    dayAgg.forEach(({ _id: day, accepted: a, total: t }) => {
      const p = t > 0 ? a / t : 0;
      byDay[day] = {
        precision: Math.round(p * 10000) / 10000,
        recall:    Math.round(p * 10000) / 10000,
        f1: p > 0 ? Math.round(((2 * p * p) / (p + p)) * 10000) / 10000 : 0,
      };
    });

    return res.json({
      success: true,
      data: {
        precision: Math.round(precision * 10000) / 10000,
        recall:    Math.round(recall    * 10000) / 10000,
        f1:        Math.round(f1        * 10000) / 10000,
        totalSamples: totalFeedback,
        byDeveloper,
        byDay,
      },
    });
  } catch (error) {
    next(error);
  }
});

module.exports = router;