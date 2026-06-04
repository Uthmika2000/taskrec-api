const express = require('express');
const router = express.Router();
const axios = require('axios');
const Assignment = require('../models/Assignment');
const Feedback = require('../models/Feedback');
const { authMiddleware } = require('../middleware/authMiddleware');

// GET /api/feedback - List feedback (with optional filters)
router.get('/', authMiddleware, async (req, res, next) => {
  try {
    const { sprintId, developerId, taskId } = req.query;
    const query = {};
    if (sprintId) query.sprintId = sprintId;
    if (developerId) query.developerId = developerId;
    if (taskId) query.taskId = taskId;

    const feedback = await Feedback.find(query)
      .populate('assignmentId')
      .populate('taskId', 'title')
      .populate('developerId', 'name email')
      .populate('sprintId', 'name')
      .sort({ createdAt: -1 });

    res.json({ success: true, data: feedback });
  } catch (error) {
    next(error);
  }
});

// GET /api/feedback/:id - Get single feedback
router.get('/:id', authMiddleware, async (req, res, next) => {
  try {
    const feedback = await Feedback.findById(req.params.id)
      .populate('assignmentId')
      .populate('taskId')
      .populate('developerId', '-passwordHash')
      .populate('sprintId');

    if (!feedback) {
      return res.status(404).json({ success: false, message: 'Feedback not found.' });
    }

    res.json({ success: true, data: feedback });
  } catch (error) {
    next(error);
  }
});

// POST /api/feedback - Log feedback on assignment (accept/reject)
//
// Accepts two calling conventions:
//   A) { taskId, developerId, action }            — from tests and feedbackAPI.submit()
//   B) { assignmentId, action }                   — from legacy accept/reject flows
//   C) { assignmentId, taskId, developerId, action } — combined
//
// Response always includes { success, data: { feedback, retrained, ... } }
// so res.body.data.feedback is always defined on success.
router.post('/', authMiddleware, async (req, res, next) => {
  try {
    const { taskId, developerId, action, assignmentId } = req.body;

    // Validate action first — return 400 before touching the DB
    if (!action || !['accept', 'reject'].includes(action)) {
      return res.status(400).json({
        success: false,
        message: 'action must be "accept" or "reject".',
      });
    }

    // Resolve or create an Assignment record
    let assignment;

    if (assignmentId) {
      // Convention B/C — update an existing assignment
      assignment = await Assignment.findByIdAndUpdate(
        assignmentId,
        { accepted: action === 'accept' },
        { new: true }
      );
      if (!assignment) {
        return res.status(404).json({ success: false, message: 'Assignment not found.' });
      }
    } else if (taskId && developerId) {
      // Convention A — create a new assignment record on the fly
      assignment = new Assignment({
        taskId,
        developerId,
        accepted: action === 'accept',
      });
      await assignment.save();
    } else {
      return res.status(400).json({
        success: false,
        message: 'Provide assignmentId or both taskId and developerId.',
      });
    }

    // Persist feedback record
    const feedback = new Feedback({
      assignmentId: assignment._id,
      action,
      taskId:      assignment.taskId,
      developerId: assignment.developerId,
      sprintId:    assignment.sprintId || null,
    });
    await feedback.save();

    // Forward to ML service for incremental retraining (non-blocking)
    const mlServiceUrl = process.env.ML_SERVICE_URL || 'http://localhost:8000';

    try {
      const mlResponse = await axios.post(
        `${mlServiceUrl}/feedback`,
        {
          taskId:      assignment.taskId.toString(),
          developerId: assignment.developerId.toString(),
          action,
        },
        { timeout: 5000 }
      );

      return res.json({
        success: true,
        data: {
          feedback,
          retrained:   mlResponse.data.retrained   ?? true,
          newAccuracy: mlResponse.data.newAccuracy ?? null,
        },
      });
    } catch (mlError) {
      // ML service down — still return success; feedback is already persisted
      console.warn('ML feedback endpoint unavailable:', mlError.message);
      return res.json({
        success: true,
        data: {
          feedback,
          retrained: false,
          message: 'Feedback logged. ML retraining deferred.',
        },
      });
    }
  } catch (error) {
    next(error);
  }
});

module.exports = router;