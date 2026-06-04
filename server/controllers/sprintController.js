const Sprint = require('../models/Sprint');
const Task = require('../models/Task');
const Team = require('../models/Team');
const { getAccessibleTeamIds } = require('../utils/access');

// @desc    Create new sprint
// @route   POST /api/sprints
// @access  Private (admin, scrum_master)
exports.createSprint = async (req, res, next) => {
  try {
    const { name, startDate, endDate, teamId, status, capacityPoints } = req.body;

    if (!teamId || !name) {
      return res.status(400).json({ success: false, message: 'teamId and name are required.' });
    }

    const team = await Team.findById(teamId);
    if (!team) {
      return res.status(404).json({ success: false, message: 'Team not found.' });
    }

    const sprint = new Sprint({
      teamId,
      name,
      startDate: startDate ? new Date(startDate) : undefined,
      endDate:   endDate   ? new Date(endDate)   : undefined,
      capacityPoints: capacityPoints || 40,
      status: status || 'PLANNING',
      taskIds: [],
    });

    await sprint.save();
    await Team.findByIdAndUpdate(teamId, { $push: { sprintIds: sprint._id } });

    const populated = await Sprint.findById(sprint._id).populate('teamId', 'name');
    return res.status(201).json({ success: true, data: populated });
  } catch (error) {
    next(error);
  }
};

// @desc    Get sprint by ID with full task + member data
// @route   GET /api/sprints/:id
// @access  Private
exports.getSprint = async (req, res, next) => {
  try {
    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);

    const sprint = await Sprint.findById(req.params.id)
      .populate({
        path: 'teamId',
        select: 'name adminId memberIds',
        populate: [
          { path: 'adminId',    select: 'name email role skillTags' },
          { path: 'memberIds',  select: 'name email role skillTags' },
        ],
      })
      .populate({
        path: 'taskIds',
        populate: [
          { path: 'assigneeId', select: 'name email skillTags' },
          // reporterId is the correct field — createdBy does not exist on Task
          { path: 'reporterId', select: 'name email' },
        ],
      });

    if (!sprint) {
      return res.status(404).json({ success: false, message: 'Sprint not found.' });
    }

    if (!accessibleTeamIds.includes(sprint.teamId._id.toString())) {
      return res.status(404).json({ success: false, message: 'Sprint not found.' });
    }

    const tasks = sprint.taskIds || [];
    const totalPoints  = tasks.reduce((s, t) => s + (t.storyPoints || 0), 0);
    const donePoints   = tasks.filter(t => t.status === 'DONE').reduce((s, t) => s + (t.storyPoints || 0), 0);
    const completionPct = totalPoints > 0 ? Math.round((donePoints / totalPoints) * 100) : 0;

    return res.json({
      success: true,
      data: {
        ...sprint.toObject(),
        stats: {
          totalTasks:        tasks.length,
          totalPoints,
          donePoints,
          completionPct,
          capacityPoints:    sprint.capacityPoints,
          remainingCapacity: Math.max(0, sprint.capacityPoints - totalPoints),
          backlog:     tasks.filter(t => t.status === 'TO_DO').length,
          inProgress:  tasks.filter(t => t.status === 'IN_PROGRESS').length,
          review:      tasks.filter(t => t.status === 'IN_REVIEW').length,
          done:        tasks.filter(t => t.status === 'DONE').length,
        },
      },
    });
  } catch (error) {
    next(error);
  }
};

// @desc    Get all sprints
// @route   GET /api/sprints?teamId=xxx&status=xxx
// @access  Private
exports.getSprints = async (req, res, next) => {
  try {
    const { teamId, status } = req.query;
    const accessibleTeamIds = await getAccessibleTeamIds(req.user._id);
    const query = {};

    if (teamId) {
      if (!accessibleTeamIds.includes(teamId)) {
        return res.json({ success: true, data: [] });
      }
      query.teamId = teamId;
    } else if (accessibleTeamIds.length > 0) {
      query.teamId = { $in: accessibleTeamIds };
    } else {
      return res.json({ success: true, data: [] });
    }

    if (status) query.status = status;

    const sprints = await Sprint.find(query)
      .populate({
        path: 'teamId',
        select: 'name adminId memberIds',
        populate: [
          { path: 'adminId',   select: 'name email role skillTags' },
          { path: 'memberIds', select: 'name email role skillTags' },
        ],
      })
      .populate({
        path: 'taskIds',
        select: 'title status storyPoints assigneeId priority',
        populate: { path: 'assigneeId', select: 'name email' },
      })
      .sort({ createdAt: -1 });

    return res.json({ success: true, data: sprints });
  } catch (error) {
    next(error);
  }
};

// @desc    Update sprint status
// @route   PATCH /api/sprints/:id/status
// @access  Private
exports.updateSprintStatus = async (req, res, next) => {
  try {
    const { status } = req.body;
    if (!status) {
      return res.status(400).json({ success: false, message: 'Status is required.' });
    }
    if (!['PLANNING', 'ACTIVE', 'COMPLETED'].includes(status)) {
      return res.status(400).json({ success: false, message: 'Invalid status. Must be PLANNING, ACTIVE, or COMPLETED.' });
    }

    const sprint = await Sprint.findByIdAndUpdate(req.params.id, { status }, { new: true })
      .populate('teamId', 'name');

    if (!sprint) {
      return res.status(404).json({ success: false, message: 'Sprint not found.' });
    }

    return res.json({ success: true, data: sprint });
  } catch (error) {
    next(error);
  }
};

// @desc    Update sprint fields
// @route   PATCH /api/sprints/:id
// @access  Private
exports.updateSprint = async (req, res, next) => {
  try {
    const allowedFields = ['name', 'startDate', 'endDate', 'status', 'capacityPoints'];
    const updates = {};

    for (const field of allowedFields) {
      if (req.body[field] === undefined) continue;
      if (field === 'startDate' || field === 'endDate') {
        updates[field] = new Date(req.body[field]);
      } else if (field === 'status') {
        if (!['PLANNING', 'ACTIVE', 'COMPLETED'].includes(req.body[field])) {
          return res.status(400).json({ success: false, message: 'Invalid status.' });
        }
        updates[field] = req.body[field];
      } else {
        updates[field] = req.body[field];
      }
    }

    const sprint = await Sprint.findByIdAndUpdate(req.params.id, updates, { new: true, runValidators: true })
      .populate('teamId', 'name')
      .populate({ path: 'taskIds', select: 'title status storyPoints' });

    if (!sprint) {
      return res.status(404).json({ success: false, message: 'Sprint not found.' });
    }

    return res.json({ success: true, data: sprint });
  } catch (error) {
    next(error);
  }
};

// @desc    Delete sprint
// @route   DELETE /api/sprints/:id
// @access  Private (admin, scrum_master)
exports.deleteSprint = async (req, res, next) => {
  try {
    const sprint = await Sprint.findById(req.params.id);
    if (!sprint) {
      return res.status(404).json({ success: false, message: 'Sprint not found.' });
    }

    if (req.query.deleteTasks === 'true') {
      await Task.deleteMany({ sprintId: req.params.id });
    } else {
      await Task.updateMany({ sprintId: req.params.id }, { sprintId: null });
    }

    await Team.updateMany({ sprintIds: req.params.id }, { $pull: { sprintIds: req.params.id } });
    await Sprint.findByIdAndDelete(req.params.id);

    return res.json({ success: true, message: 'Sprint deleted successfully.' });
  } catch (error) {
    next(error);
  }
};

// @desc    Clone sprint
// @route   POST /api/sprints/:id/clone
// @access  Private (admin, scrum_master)
exports.cloneSprint = async (req, res, next) => {
  try {
    const originalSprint = await Sprint.findById(req.params.id).populate({ path: 'taskIds' });
    if (!originalSprint) {
      return res.status(404).json({ success: false, message: 'Sprint not found.' });
    }

    const newSprint = new Sprint({
      teamId:    originalSprint.teamId,
      name:      req.body.name || `${originalSprint.name} (Copy)`,
      startDate: new Date(),
      endDate:   new Date(Date.now() + 14 * 24 * 60 * 60 * 1000),
      status:    'PLANNING',
      taskIds:   [],
    });
    await newSprint.save();

    if (originalSprint.taskIds?.length > 0) {
      const clonedIds = [];
      for (const t of originalSprint.taskIds) {
        const newTask = new Task({
          sprintId:    newSprint._id,
          title:       t.title,
          description: t.description,
          storyPoints: t.storyPoints,
          priority:    t.priority,
          status:      'TO_DO',
          assigneeId:  null,
          reporterId:  t.reporterId,
        });
        await newTask.save();
        clonedIds.push(newTask._id);
      }
      newSprint.taskIds = clonedIds;
      await newSprint.save();
    }

    await Team.findByIdAndUpdate(newSprint.teamId, { $push: { sprintIds: newSprint._id } });

    const populated = await Sprint.findById(newSprint._id)
      .populate('teamId', 'name')
      .populate({ path: 'taskIds', select: 'title status storyPoints' });

    return res.status(201).json({ success: true, data: populated });
  } catch (error) {
    next(error);
  }
};

// @desc    Start sprint (PLANNING -> ACTIVE)
// @route   PATCH /api/sprints/:id/start
// @access  Private (admin, scrum_master)
exports.startSprint = async (req, res, next) => {
  try {
    const sprint = await Sprint.findById(req.params.id);
    if (!sprint) {
      return res.status(404).json({ success: false, message: 'Sprint not found.' });
    }
    if (sprint.status !== 'PLANNING') {
      return res.status(400).json({ success: false, message: 'Only PLANNING sprints can be started.' });
    }
    const active = await Sprint.findOne({ teamId: sprint.teamId, status: 'ACTIVE' });
    if (active) {
      return res.status(400).json({ success: false, message: 'Team already has an active sprint.' });
    }

    sprint.status    = 'ACTIVE';
    sprint.startDate = new Date();
    await sprint.save();

    const populated = await Sprint.findById(sprint._id).populate('teamId', 'name');
    return res.json({ success: true, data: populated });
  } catch (error) {
    next(error);
  }
};

// @desc    Complete sprint (ACTIVE -> COMPLETED)
// @route   PATCH /api/sprints/:id/complete
// @access  Private (admin, scrum_master)
exports.completeSprint = async (req, res, next) => {
  try {
    const sprint = await Sprint.findById(req.params.id);
    if (!sprint) {
      return res.status(404).json({ success: false, message: 'Sprint not found.' });
    }
    if (sprint.status !== 'ACTIVE') {
      return res.status(400).json({ success: false, message: 'Only ACTIVE sprints can be completed.' });
    }

    sprint.status  = 'COMPLETED';
    sprint.endDate = new Date();
    await sprint.save();

    const populated = await Sprint.findById(sprint._id).populate('teamId', 'name');
    return res.json({ success: true, data: populated });
  } catch (error) {
    next(error);
  }
};