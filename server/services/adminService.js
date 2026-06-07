const axios = require('axios');
const Task = require('../models/Task');
const Sprint = require('../models/Sprint');
const Team = require('../models/Team');
const User = require('../models/User');
const Recommendation = require('../models/Recommendation');
const Feedback = require('../models/Feedback');
const { ML } = require('../constants');

async function getStats() {
  const [totalUsers, totalTeams, totalTasks, activeSprints, totalRecommendations, feedbackCount] = await Promise.all([
    User.countDocuments({ isActive: true }),
    Team.countDocuments(),
    Task.countDocuments(),
    Sprint.countDocuments({ status: 'ACTIVE' }),
    Recommendation.countDocuments(),
    Feedback.countDocuments(),
  ]);

  return { totalUsers, totalTeams, totalTasks, activeSprints, totalRecommendations, feedbackCount };
}

async function getModelStatus() {
  const [totalSamples, lastFeedback] = await Promise.all([
    Feedback.countDocuments(),
    Feedback.findOne().sort({ createdAt: -1 }).select('createdAt'),
  ]);
  return {
    totalTrainingSamples: totalSamples,
    lastFeedbackAt:       lastFeedback ? lastFeedback.createdAt : null,
  };
}

async function triggerRetrain() {
  const mlServiceUrl = process.env.ML_SERVICE_URL || 'http://localhost:8000';

  const [developers, tasks, feedback] = await Promise.all([
    User.find({ role: 'developer' }).select('name skillTags'),
    Task.find().select('title description'),
    Feedback.find().select('taskId developerId action'),
  ]);

  const payload = {
    developers: developers.map(d => ({
      id: d._id.toString(),
      name: d.name,
      skillTags: d.skillTags || [],
    })),
    tasks: tasks.map(t => ({
      id: t._id.toString(),
      description: `${t.title} ${t.description}`.trim(),
      title: t.title,
    })),
    assignments: feedback.map(f => ({
      developer_id: f.developerId.toString(),
      task_id: f.taskId.toString(),
      accepted: f.action === 'accept',
    })),
  };

  // Retraining encodes many tasks, so allow a generous timeout.
  const res = await axios.post(`${mlServiceUrl}/retrain`, payload, { timeout: 120000 });
  return res.data;
}

module.exports = { getStats, getModelStatus, triggerRetrain };