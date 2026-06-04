const express = require('express');
const router = express.Router();
const Assignment = require('../models/Assignment');
const { authMiddleware } = require('../middleware/authMiddleware');

// GET /api/assignments - List all assignments (with optional filters)
router.get('/', authMiddleware, async (req, res, next) => {
  try {
    const { sprintId, developerId, taskId } = req.query;
    const query = {};
    if (sprintId) query.sprintId = sprintId;
    if (developerId) query.developerId = developerId;
    if (taskId) query.taskId = taskId;

    const assignments = await Assignment.find(query)
      .populate('taskId', 'title sprintId')
      .populate('developerId', 'name email skillTags')
      .populate('sprintId', 'name')
      .sort({ createdAt: -1 });

    res.json({ success: true, data: assignments });
  } catch (error) {
    next(error);
  }
});

// GET /api/assignments/:id - Get single assignment
router.get('/:id', authMiddleware, async (req, res, next) => {
  try {
    const assignment = await Assignment.findById(req.params.id)
      .populate('taskId')
      .populate('developerId', '-passwordHash')
      .populate('sprintId');

    if (!assignment) {
      return res.status(404).json({ success: false, message: 'Assignment not found.' });
    }

    res.json({ success: true, data: assignment });
  } catch (error) {
    next(error);
  }
});

module.exports = router;
