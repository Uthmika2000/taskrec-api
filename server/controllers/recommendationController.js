const axios = require('axios');
const Task = require('../models/Task');
const User = require('../models/User');
const Sprint = require('../models/Sprint');
const Recommendation = require('../models/Recommendation');
const Feedback = require('../models/Feedback');
const { getAccessibleTeamIds } = require('../utils/access');

// @desc    Get recommendation for a task
// @route   GET /api/recommend/:taskId  (frontend)
// @route   POST /api/recommendations/task/:taskId  (legacy / role-gated)
// @access  Private
exports.getRecommendation = async (req, res, next) => {
  try {
    // Works for both GET /:taskId and POST /task/:taskId
    const taskId = req.params.taskId || req.params.id;

    const task = await Task.findById(taskId).populate('sprintId');

    if (!task) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    // Resolve teamId safely through sprintId (task may not have a direct teamId field)
    const teamId = task.teamId ?? task.sprintId?.teamId;
    if (!teamId) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);
    if (!accessibleTeamIds.includes(teamId.toString())) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    // Fetch the sprint with team data
    const sprint = await Sprint.findById(task.sprintId._id ?? task.sprintId).populate({
      path: 'teamId',
      select: '_id memberIds adminId',
    });

    if (!sprint) {
      return res.status(404).json({ success: false, message: 'Sprint not found' });
    }

    const teamMemberIds = sprint.teamId?.memberIds || [];
    const developers = await User.find({
      _id: { $in: teamMemberIds },
      role: 'developer',
    }).select('-passwordHash');

    if (developers.length === 0) {
      return res.json({
        success: true,
        data: {
          recommendations: [],
          message: 'No developers in this sprint team',
          cold_start: true,
        },
      });
    }

    // Build per-developer workload map (exclude the task being assigned)
    const sprintTasks = await Task.find({ sprintId: sprint._id });
    const workloads = {};
    developers.forEach(d => {
      workloads[d._id.toString()] = sprintTasks
        .filter(
          t =>
            t.assigneeId?.toString() === d._id.toString() &&
            t._id.toString() !== task._id.toString()
        )
        .reduce((sum, t) => sum + (t.storyPoints || 0), 0);
    });

    const mlServiceUrl = process.env.ML_SERVICE_URL || 'http://localhost:8000';

    try {
      // Build workloads map as { developerId: storyPoints } — main.py reads request.workloads
      const workloadsPayload = {};
      developers.forEach(d => {
        workloadsPayload[d._id.toString()] = workloads[d._id.toString()] || 0;
      });

      // AssignmentInput: { developerId, taskId, accepted }
      // Build from sprint tasks that already have an assignee (all accepted=true
      // since they were assigned). Exclude the task currently being recommended.
      const assignmentsPayload = sprintTasks
        .filter(t => t.assigneeId && t._id.toString() !== task._id.toString())
        .map(t => ({
          taskId:      t._id.toString(),
          developerId: t.assigneeId.toString(),
          accepted:    true,
        }));

      const mlRequest = {
        // TaskInput: { id, description }  — title is not in the schema, omit it
        task: {
          id: task._id.toString(),
          description: `${task.title} ${task.description}`.trim(),
        },
        // DeveloperInput: { id, name, skillTags }  — all camelCase, no extras
        developers: developers.map(d => ({
          id: d._id.toString(),
          name: d.name,
          skillTags: d.skillTags || [],
        })),
        // AssignmentInput: { developerId, taskId, accepted }
        assignments: assignmentsPayload,
        // workloads: { [developerId]: storyPoints }
        workloads: workloadsPayload,
        // sprintCapacity: int
        sprintCapacity: sprint.capacityPoints || 40,
      };

      const mlResponse = await axios.post(`${mlServiceUrl}/recommend`, mlRequest, {
        timeout: 10000,
      });

      // main.py returns RecommendationItem with camelCase fields:
      //   developerId, name, score, breakdown { nlp, cf, capacity }, skillTags, cold_start
      const mlRecs = mlResponse.data.recommendations || [];

      const recommendation = new Recommendation({
        taskId: task._id,
        requestedBy: req.user._id,
        results: mlRecs.map(r => ({
          developerId:   r.developerId,
          nlpScore:      r.breakdown?.nlp      ?? 0.5,
          cfScore:       r.breakdown?.cf       ?? 0.5,
          capacityScore: r.breakdown?.capacity ?? 0.5,
          combinedScore: r.score ?? 0,
          reasoning: r.reasoning || 'Recommended based on matching skills and capacity',
        })),
      });
      await recommendation.save();

      // Return top 3 — breakdown keys (nlp/cf/capacity) already match frontend
      const topRecs = mlRecs.slice(0, 3).map(r => ({
        developerId: r.developerId,
        name: r.name,
        score: r.score ?? 0,
        breakdown: {
          nlp:      r.breakdown?.nlp      ?? 0.5,
          cf:       r.breakdown?.cf       ?? 0.5,
          capacity: r.breakdown?.capacity ?? 0.5,
        },
        reasoning: r.reasoning || 'Based on historical patterns and current workload',
        skillTags: r.skillTags || developers.find(d => d._id.toString() === r.developerId)?.skillTags || [],
      }));

      return res.json({
        success: true,
        data: {
          recommendationId: recommendation._id,
          recommendations: topRecs,
          cold_start: mlResponse.data.cold_start || false,
        },
      });
    } catch (mlError) {
      console.warn('ML service unavailable, using local fallback:', mlError.message);

      const localRecs = generateLocalRecommendations(
        task,
        developers,
        workloads,
        sprint.capacityPoints || 40
      );

      const recommendation = new Recommendation({
        taskId: task._id,
        requestedBy: req.user._id,
        results: localRecs.map(r => ({
          developerId: r.developerId,
          nlpScore: r.nlpScore,
          cfScore: 0.5, // neutral CF in cold-start
          capacityScore: r.capacityScore,
          combinedScore: r.score,
          reasoning: r.reasoning,
        })),
      });
      await recommendation.save();

      // Fallback also uses the short breakdown keys the frontend expects
      const topLocalRecs = localRecs.slice(0, 3).map(r => ({
        developerId: r.developerId,
        name: r.name,
        score: r.score,
        breakdown: {
          nlp: r.nlpScore,
          cf: 0.5,
          capacity: r.capacityScore,
        },
        reasoning: r.reasoning,
        skillTags: r.skillTags,
      }));

      return res.json({
        success: true,
        data: {
          recommendationId: recommendation._id,
          recommendations: topLocalRecs,
          cold_start: true,
          warning: 'ML service unavailable — using fallback recommendation',
        },
      });
    }
  } catch (error) {
    next(error);
  }
};

// @desc    Accept recommendation and assign developer
// @route   POST /api/recommendations/accept
// @access  Private
exports.acceptRecommendation = async (req, res, next) => {
  try {
    const { recommendationId, taskId, developerId } = req.body;

    if (!recommendationId || !taskId || !developerId) {
      return res
        .status(400)
        .json({ success: false, message: 'recommendationId, taskId, and developerId required' });
    }

    const recommendation = await Recommendation.findById(recommendationId);
    if (!recommendation) {
      return res.status(404).json({ success: false, message: 'Recommendation not found' });
    }

    recommendation.accepted = true;
    recommendation.acceptedDeveloperId = developerId;
    await recommendation.save();

    const task = await Task.findByIdAndUpdate(
      taskId,
      { assigneeId: developerId },
      { new: true }
    )
      .populate('assigneeId', '-passwordHash')
      .populate('reporterId', '-passwordHash');

    const feedback = new Feedback({
      taskId,
      developerId,
      action: 'accept',
      timestamp: new Date(),
    });
    await feedback.save();

    return res.json({
      success: true,
      message: 'Developer assigned successfully',
      data: task,
    });
  } catch (error) {
    next(error);
  }
};

// @desc    Reject recommendation and assign manually
// @route   POST /api/recommendations/reject
// @access  Private
exports.rejectRecommendation = async (req, res, next) => {
  try {
    const { recommendationId, taskId, developerId } = req.body;

    if (!recommendationId || !taskId) {
      return res
        .status(400)
        .json({ success: false, message: 'recommendationId and taskId required' });
    }

    const recommendation = await Recommendation.findById(recommendationId);
    if (recommendation) {
      recommendation.accepted = false;
      await recommendation.save();
    }

    const task = await Task.findByIdAndUpdate(
      taskId,
      { assigneeId: developerId || null },
      { new: true }
    )
      .populate('assigneeId', '-passwordHash')
      .populate('reporterId', '-passwordHash');

    if (developerId) {
      const feedback = new Feedback({
        taskId,
        developerId,
        action: 'reject',
        timestamp: new Date(),
      });
      await feedback.save();
    }

    return res.json({
      success: true,
      message: 'Manual assignment completed',
      data: task,
    });
  } catch (error) {
    next(error);
  }
};

// @desc    Log accept/reject feedback (unified endpoint for tests + frontend)
// @route   POST /api/feedback
// @access  Private
exports.logFeedback = async (req, res, next) => {
  try {
    const { taskId, developerId, action } = req.body;

    if (!taskId || !developerId || !action) {
      return res
        .status(400)
        .json({ success: false, message: 'taskId, developerId and action are required' });
    }

    if (!['accept', 'reject'].includes(action)) {
      return res
        .status(400)
        .json({ success: false, message: 'action must be "accept" or "reject"' });
    }

    const feedback = await Feedback.create({
      taskId,
      developerId,
      action,
      timestamp: new Date(),
    });

    return res.json({ success: true, data: { feedback } });
  } catch (error) {
    next(error);
  }
};

// @desc    Get stored recommendation for a task
// @route   GET /api/recommendations/task/:taskId
// @access  Private
exports.getRecommendationByTask = async (req, res, next) => {
  try {
    const recommendation = await Recommendation.findOne({ taskId: req.params.taskId })
      .populate('taskId')
      .populate('requestedBy', 'name email')
      .sort({ createdAt: -1 });

    return res.json({ success: true, data: recommendation || null });
  } catch (error) {
    next(error);
  }
};

// @desc    Get all recommendations
// @route   GET /api/recommendations
// @access  Private
exports.getRecommendations = async (req, res, next) => {
  try {
    const { taskId } = req.query;
    const query = {};
    if (taskId) query.taskId = taskId;

    const recommendations = await Recommendation.find(query)
      .populate('taskId')
      .populate('requestedBy', 'name email')
      .sort({ createdAt: -1 });

    return res.json({ success: true, data: recommendations });
  } catch (error) {
    next(error);
  }
};

// ─── Local fallback ───────────────────────────────────────────────────────────
function generateLocalRecommendations(task, developers, workloads, sprintCapacity) {
  return developers
    .map(dev => {
      const taskText = `${task.title} ${task.description}`.toLowerCase();

      let nlpScore = 0.5;
      if (dev.skillTags && dev.skillTags.length > 0) {
        let matchCount = 0;
        dev.skillTags.forEach(skill => {
          if (taskText.includes(skill.toLowerCase())) matchCount++;
        });
        nlpScore = Math.min(1, 0.3 + (matchCount / Math.max(1, dev.skillTags.length)) * 0.7);
      }

      const devWorkload = workloads[dev._id.toString()] || 0;
      const capacityScore = Math.max(0, 1 - devWorkload / sprintCapacity);

      // Weights match the formula shown in the UI (NLP 0.4, CF neutral 0.4→0.5, capacity -0.2)
      const score = nlpScore * 0.4 + 0.5 * 0.4 + capacityScore * 0.2;

      return {
        developerId: dev._id.toString(),
        name: dev.name,
        score,
        nlpScore,
        capacityScore,
        skillTags: dev.skillTags || [],
        reasoning: `${Math.round(nlpScore * 100)}% skill match, ${Math.round(capacityScore * 100)}% capacity available`,
      };
    })
    .sort((a, b) => b.score - a.score);
}