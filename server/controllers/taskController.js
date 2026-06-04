// Task Controller - Backend MVC Architecture
const Task = require('../models/Task');
const Sprint = require('../models/Sprint');
const Assignment = require('../models/Assignment');
const { getAccessibleTeamIds } = require('../utils/access');

// @desc    Create new task
// @route   POST /api/tasks
// @access  Private
exports.createTask = async (req, res, next) => {
  try {
    const { title, description, status, priority, storyPoints, sprintId, assigneeId } = req.body;

    // Validate required fields
    if (!title || !sprintId || !description) {
      return res.status(400).json({ success: false, message: 'Title, Sprint ID and description are required' });
    }

    // Check if sprint exists
    const sprint = await Sprint.findById(sprintId);
    if (!sprint) {
      return res.status(404).json({ success: false, message: 'Sprint not found' });
    }

    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);
    if (!accessibleTeamIds.includes(sprint.teamId.toString())) {
      return res.status(404).json({ success: false, message: 'Sprint not found' });
    }

    const { type, componentLabels } = req.body;
    
    const task = await Task.create({
      title,
      description,
      type: type || 'TASK',
      status: status || 'TO_DO',
      priority: priority?.toUpperCase() || 'MEDIUM',
      storyPoints: storyPoints || 1,
      componentLabels: componentLabels || [],
      sprintId,
      teamId: sprint.teamId,
      assigneeId: assigneeId || null,
      reporterId: req.user._id,
    });

    // Populate references
    const populated = await Task.findById(task._id)
      .populate('assigneeId', '-passwordHash')
      .populate('reporterId', '-passwordHash');

    res.status(201).json({ success: true, data: populated });
  } catch (error) {
    next(error);
  }
};

// @desc    Get task by ID
// @route   GET /api/tasks/:id
// @access  Private
exports.getTask = async (req, res, next) => {
  try {
    const task = await Task.findById(req.params.id)
      .populate('sprintId')
      .populate('assigneeId', '-passwordHash')
      .populate('reporterId', '-passwordHash');

    if (!task) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);
    if (!accessibleTeamIds.includes(task.sprintId.teamId.toString())) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    res.json({ success: true, data: task });
  } catch (error) {
    next(error);
  }
};

// @desc    Get all tasks (with optional sprint filter)
// @route   GET /api/tasks?sprintId=xxx
// @access  Private
exports.getTasks = async (req, res, next) => {
  try {
    const { sprintId } = req.query;
    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);

    let filter = {};
    if (sprintId) {
      const sprint = await Sprint.findById(sprintId).select('teamId');
      if (!sprint || !accessibleTeamIds.includes(sprint.teamId.toString())) {
        return res.json({ success: true, data: [] });
      }
      filter = { sprintId };
    } else {
      const accessibleSprints = await Sprint.find({ teamId: { $in: accessibleTeamIds } }).select('_id');
      filter = { sprintId: { $in: accessibleSprints.map(sprint => sprint._id) } };
    }

    const tasks = await Task.find(filter)
      .populate('assigneeId', '-passwordHash')
      .populate('reporterId', '-passwordHash')
      .populate('sprintId', 'name')
      .sort({ createdAt: -1 });

    res.json({ success: true, data: tasks });
  } catch (error) {
    next(error);
  }
};

// @desc    Update task
// @route   PATCH /api/tasks/:id
// @access  Private
exports.updateTask = async (req, res, next) => {
  try {
    const allowedUpdates = ['title', 'description', 'status', 'priority', 'storyPoints', 'assigneeId'];
    const updates = {};

    allowedUpdates.forEach(field => {
      if (req.body[field] !== undefined) updates[field] = req.body[field];
    });

    const task = await Task.findByIdAndUpdate(req.params.id, updates, { new: true })
      .populate('assigneeId', '-passwordHash')
      .populate('reporterId', '-passwordHash');

    if (!task) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);
    const taskSprint = await Sprint.findById(task.sprintId).select('teamId');
    if (!taskSprint || !accessibleTeamIds.includes(taskSprint.teamId.toString())) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    res.json({ success: true, data: task });
  } catch (error) {
    next(error);
  }
};

// @desc    Delete task
// @route   DELETE /api/tasks/:id
// @access  Private
exports.deleteTask = async (req, res, next) => {
  try {
    const task = await Task.findById(req.params.id);
    if (!task) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);
    const taskSprint = await Sprint.findById(task.sprintId).select('teamId');
    if (!taskSprint || !accessibleTeamIds.includes(taskSprint.teamId.toString())) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    await Task.findByIdAndDelete(req.params.id);

    // Clean up assignments for this task
    await Assignment.deleteMany({ taskId: req.params.id });

    res.json({ success: true, message: 'Task deleted successfully' });
  } catch (error) {
    next(error);
  }
};

// @desc    Assign task to developer
// @route   PATCH /api/tasks/:id/assign
// @access  Private
exports.assignTask = async (req, res, next) => {
  try {
    const { assigneeId } = req.body;

    const task = await Task.findById(req.params.id);
    if (!task) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);
    const taskSprint = await Sprint.findById(task.sprintId).select('teamId');
    if (!taskSprint || !accessibleTeamIds.includes(taskSprint.teamId.toString())) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    // Update task assignee
    task.assigneeId = assigneeId || null;
    await task.save();

    // Log assignment to Assignment collection
    if (assigneeId) {
      const assignment = new Assignment({
        taskId: task._id,
        developerId: assigneeId,
        accepted: true,
        sprintId: task.sprintId,
      });
      await assignment.save();
    }

    const populated = await Task.findById(task._id)
      .populate('assigneeId', '-passwordHash')
      .populate('reporterId', '-passwordHash');

    res.json({ success: true, data: populated });
  } catch (error) {
    next(error);
  }
};

// @desc    Update task status
// @route   PATCH /api/tasks/:id/status
// @access  Private
exports.updateTaskStatus = async (req, res, next) => {
  try {
    const { status } = req.body;

    if (!['TO_DO', 'IN_PROGRESS', 'IN_REVIEW', 'DONE'].includes(status)) {
      return res.status(400).json({ success: false, message: 'Invalid status value' });
    }

    const task = await Task.findByIdAndUpdate(
      req.params.id,
      { status },
      { new: true }
    )
      .populate('assigneeId', '-passwordHash')
      .populate('reporterId', '-passwordHash');

    if (!task) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);
    if (!accessibleTeamIds.includes(task.teamId.toString())) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    res.json({ success: true, data: task });
  } catch (error) {
    next(error);
  }
};

// @desc    Add comment to task
// @route   POST /api/tasks/:id/comments
// @access  Private
exports.addComment = async (req, res, next) => {
  try {
    const { text } = req.body;

    if (!text || !text.trim()) {
      return res.status(400).json({ success: false, message: 'Comment text is required' });
    }

    const task = await Task.findById(req.params.id);
    if (!task) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);
    if (!accessibleTeamIds.includes(task.teamId.toString())) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    task.comments.push({
      authorId: req.user._id,
      text: text.trim(),
      createdAt: new Date(),
    });

    await task.save();

    const populated = await Task.findById(task._id)
      .populate('assigneeId', '-passwordHash')
      .populate('reporterId', '-passwordHash')
      .populate('comments.authorId', 'name email');

    res.status(201).json({ success: true, data: populated });
  } catch (error) {
    next(error);
  }
};

// @desc    Get task comments
// @route   GET /api/tasks/:id/comments
// @access  Private
exports.getComments = async (req, res, next) => {
  try {
    const task = await Task.findById(req.params.id).populate('comments.authorId', 'name email');

    if (!task) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);
    if (!accessibleTeamIds.includes(task.teamId.toString())) {
      return res.status(404).json({ success: false, message: 'Task not found' });
    }

    res.json({ success: true, data: task.comments });
  } catch (error) {
    next(error);
  }
};
